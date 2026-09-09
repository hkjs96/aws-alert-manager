"""
알림 정제 설정 — DB에서 읽는 정책과 정비창 (R3-9, tasks 1.4.4 / 1.4.6)

지금까지 정제 설정은 환경변수였다. 값을 바꾸려면 배포가 필요했고, 정비창(silence)은
정책 객체에만 존재해 실제로는 **한 번도 적용되지 않았다**. 이 모듈이 둘 다 DB로 옮긴다.

    AlertPolicyTable   PK config_type / SK config_id
      ("policy",  "default")   전역 정제 정책 — 없으면 환경변수, 그것도 없으면 코드 기본값
      ("silence", "{id}")      정비창 — ttl = ends_at + 7일 (짧은 감사 흔적 뒤 자동 삭제)

**우선순위: DB > 환경변수 > 코드 기본값.** DB 항목에 있는 필드만 덮어쓰므로 부분 저장이 되고,
DB가 비었거나 읽기에 실패해도 이전과 똑같이 동작한다.

**범위를 벗어난 값은 로더가 클램프하고, API가 거절한다.** 둘의 역할이 다르다 — 사람이 값을
넣을 때는 틀렸다고 알려야 하고(400), 런타임은 이미 저장된 이상한 값 때문에 멈추면 안 된다.
정제 설정이 잘못되면 **알림이 전부 사라질 수 있다**. 그래서 상한을 둔다:
재알림 주기가 하루를 넘거나 정비창이 한 달을 넘으면 그건 설정이 아니라 사고다.

아래 순수 함수는 저장소를 모른다. 유일한 IO는 맨 아래 `load_cached()`이며,
인제스터와 그룹 워커가 이것을 공유한다(중복 구현 방지).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from common.alert_suppression import Silence, SuppressionPolicy

logger = logging.getLogger(__name__)

CONFIG_POLICY = "policy"
CONFIG_SILENCE = "silence"
POLICY_DEFAULT = "default"

#: 설정 캐시 수명. 정비창을 만든 사람이 1분 안에 효과를 볼 수 있어야 하고,
#: 이벤트마다 읽으면 비용·지연이 붙는다.
CONFIG_CACHE_TTL_SEC = 60

#: 정비창을 지운 뒤에도 잠깐 남겨 "왜 그때 안 왔나"를 설명할 수 있게 한다.
SILENCE_RETENTION_DAYS = 7
MAX_SILENCE_DAYS = 30

#: 정수/실수 필드의 허용 범위 (min, max). 밖이면 클램프(로더) 또는 400(API).
POLICY_LIMITS: dict[str, tuple[float, float]] = {
    "repeat_interval_sec": (0, 86_400),
    "flapping_quarantine_sec": (0, 86_400),
    "flapping_per_day": (1, 1_000),
    "flapping_window_days": (1 / 24, 30),
    "group_wait_sec": (0, 300),
    # 0 = 재알림 없음. 상한 하루 — 그보다 길면 재알림이 아니라 방치다.
    "renotify_after_sec": (0, 86_400),
}
AUTO_PAUSE_LIMITS = (0, 3_600)
_INT_FIELDS = ("repeat_interval_sec", "flapping_quarantine_sec", "flapping_per_day",
               "group_wait_sec", "renotify_after_sec")
_FLOAT_FIELDS = ("flapping_window_days",)


class ConfigError(ValueError):
    """사람이 넣은 값이 규칙을 어겼다 — API가 400으로 돌려준다."""


# ────────────────────────────────── 순수 로직

def _clamp(name: str, value: float) -> float:
    lo, hi = POLICY_LIMITS[name]
    if value < lo or value > hi:
        logger.warning("policy %s=%s is out of range [%s, %s] — clamping", name, value, lo, hi)
    return max(lo, min(hi, value))


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_from_item(base: SuppressionPolicy, item: dict | None) -> SuppressionPolicy:
    """DB 정책 항목을 기준 정책 위에 덮어쓴다. 항목에 없는 필드는 그대로 둔다."""
    if not item:
        return base
    kwargs: dict = {
        "auto_pause_sec": dict(base.auto_pause_sec),
        "repeat_interval_sec": base.repeat_interval_sec,
        "exempt_severities": base.exempt_severities,
        "flapping_window_days": base.flapping_window_days,
        "flapping_per_day": base.flapping_per_day,
        "flapping_quarantine_sec": base.flapping_quarantine_sec,
        "group_wait_sec": base.group_wait_sec,
        "silences": base.silences,
    }
    raw_pause = item.get("auto_pause_sec")
    if isinstance(raw_pause, dict):
        pause: dict[str, int] = {}
        for sev, value in raw_pause.items():
            try:
                pause[str(sev)] = int(max(AUTO_PAUSE_LIMITS[0], min(AUTO_PAUSE_LIMITS[1], int(value))))
            except (TypeError, ValueError):
                logger.warning("policy auto_pause_sec[%s]=%r is not a number — ignoring", sev, value)
        kwargs["auto_pause_sec"] = pause
    for name in _INT_FIELDS:
        if item.get(name) is not None:
            try:
                kwargs[name] = int(_clamp(name, int(item[name])))
            except (TypeError, ValueError):
                logger.warning("policy %s=%r is not a number — keeping %s", name, item[name], kwargs[name])
    for name in _FLOAT_FIELDS:
        if item.get(name) is not None:
            try:
                kwargs[name] = float(_clamp(name, float(item[name])))
            except (TypeError, ValueError):
                logger.warning("policy %s=%r is not a number — keeping %s", name, item[name], kwargs[name])
    exempt = item.get("exempt_severities")
    if isinstance(exempt, (list, tuple, set)):
        kwargs["exempt_severities"] = tuple(sorted({str(s) for s in exempt if str(s).strip()}))
    return SuppressionPolicy(**kwargs)


def policy_to_item(policy: SuppressionPolicy, *, updated_by: str = "") -> dict:
    return {
        "config_type": CONFIG_POLICY,
        "config_id": POLICY_DEFAULT,
        "auto_pause_sec": {k: int(v) for k, v in policy.auto_pause_sec.items()},
        "repeat_interval_sec": int(policy.repeat_interval_sec),
        "exempt_severities": list(policy.exempt_severities),
        "flapping_window_days": str(policy.flapping_window_days),   # DynamoDB는 float를 거부한다
        "flapping_per_day": int(policy.flapping_per_day),
        "flapping_quarantine_sec": int(policy.flapping_quarantine_sec),
        "group_wait_sec": int(policy.group_wait_sec),
        "updated_at": iso(datetime.now(timezone.utc)),
        "updated_by": updated_by,
    }


def policy_to_dict(policy: SuppressionPolicy) -> dict:
    """API 응답용. 정비창은 별도 엔드포인트라 포함하지 않는다."""
    return {
        "auto_pause_sec": {k: int(v) for k, v in sorted(policy.auto_pause_sec.items())},
        "repeat_interval_sec": int(policy.repeat_interval_sec),
        "exempt_severities": list(policy.exempt_severities),
        "flapping_window_days": float(policy.flapping_window_days),
        "flapping_per_day": int(policy.flapping_per_day),
        "flapping_quarantine_sec": int(policy.flapping_quarantine_sec),
        "group_wait_sec": int(policy.group_wait_sec),
    }


def silence_from_item(item: dict) -> Silence | None:
    """DB 항목 → Silence. 시각이 없거나 뒤집혔으면 버린다(적용되지 않는다)."""
    starts, ends = parse_dt(item.get("starts_at")), parse_dt(item.get("ends_at"))
    if starts is None or ends is None or ends <= starts:
        logger.warning("silence %s has invalid window — ignoring", item.get("config_id"))
        return None
    return Silence(
        starts_at=starts, ends_at=ends,
        customer_id=str(item.get("customer_id", "") or ""),
        resource_type=str(item.get("resource_type", "") or ""),
        reason=str(item.get("reason", "") or ""),
    )


def silences_from_items(items: list[dict]) -> tuple[Silence, ...]:
    return tuple(s for s in (silence_from_item(i) for i in (items or [])) if s is not None)


def new_silence_id(now: datetime) -> str:
    """시간 접두사 — 정렬키가 곧 생성 순서가 된다."""
    return f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def silence_to_item(silence: Silence, *, config_id: str, created_by: str = "",
                    created_at: datetime | None = None) -> dict:
    created_at = created_at or datetime.now(timezone.utc)
    return {
        "config_type": CONFIG_SILENCE,
        "config_id": config_id,
        "starts_at": iso(silence.starts_at),
        "ends_at": iso(silence.ends_at),
        "customer_id": silence.customer_id,
        "resource_type": silence.resource_type,
        "reason": silence.reason,
        "created_by": created_by,
        "created_at": iso(created_at),
        "ttl": int((silence.ends_at + timedelta(days=SILENCE_RETENTION_DAYS)).timestamp()),
    }


def silence_to_dict(item: dict, *, now: datetime) -> dict:
    """API 응답용 — 지금 적용 중인지(`active`)를 함께 준다."""
    starts, ends = parse_dt(item.get("starts_at")), parse_dt(item.get("ends_at"))
    active = bool(starts and ends and starts <= now < ends)
    return {
        "id": str(item.get("config_id", "")),
        "starts_at": str(item.get("starts_at", "")),
        "ends_at": str(item.get("ends_at", "")),
        "customer_id": str(item.get("customer_id", "") or ""),
        "resource_type": str(item.get("resource_type", "") or ""),
        "reason": str(item.get("reason", "") or ""),
        "created_by": str(item.get("created_by", "") or ""),
        "created_at": str(item.get("created_at", "") or ""),
        "active": active,
        "expired": bool(ends and now >= ends),
    }


def validate_policy(body: dict, base: SuppressionPolicy) -> SuppressionPolicy:
    """API 입력 → 정책. 범위를 벗어나면 ConfigError. 없는 필드는 기준값을 유지한다."""
    if not isinstance(body, dict):
        raise ConfigError("요청 본문이 객체가 아닙니다")
    kwargs: dict = {
        "auto_pause_sec": dict(base.auto_pause_sec),
        "repeat_interval_sec": base.repeat_interval_sec,
        "exempt_severities": base.exempt_severities,
        "flapping_window_days": base.flapping_window_days,
        "flapping_per_day": base.flapping_per_day,
        "flapping_quarantine_sec": base.flapping_quarantine_sec,
        "group_wait_sec": base.group_wait_sec,
    }
    if "auto_pause_sec" in body:
        raw = body["auto_pause_sec"]
        if not isinstance(raw, dict):
            raise ConfigError("auto_pause_sec는 {등급: 초} 객체여야 합니다")
        pause: dict[str, int] = {}
        for sev, value in raw.items():
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                raise ConfigError(f"auto_pause_sec[{sev}]는 정수여야 합니다") from None
            if not AUTO_PAUSE_LIMITS[0] <= seconds <= AUTO_PAUSE_LIMITS[1]:
                raise ConfigError(
                    f"auto_pause_sec[{sev}]는 {AUTO_PAUSE_LIMITS[0]}~{AUTO_PAUSE_LIMITS[1]}초 범위여야 합니다")
            pause[str(sev)] = seconds
        kwargs["auto_pause_sec"] = pause
    for name in _INT_FIELDS + _FLOAT_FIELDS:
        if name not in body:
            continue
        caster = int if name in _INT_FIELDS else float
        try:
            value = caster(body[name])
        except (TypeError, ValueError):
            raise ConfigError(f"{name}는 숫자여야 합니다") from None
        lo, hi = POLICY_LIMITS[name]
        if not lo <= value <= hi:
            raise ConfigError(f"{name}는 {lo}~{hi} 범위여야 합니다")
        kwargs[name] = value
    if "exempt_severities" in body:
        raw = body["exempt_severities"]
        if not isinstance(raw, (list, tuple)):
            raise ConfigError("exempt_severities는 배열이어야 합니다")
        kwargs["exempt_severities"] = tuple(sorted({str(s).strip() for s in raw if str(s).strip()}))
    return SuppressionPolicy(**kwargs)


def validate_silence(body: dict, *, now: datetime) -> Silence:
    """API 입력 → Silence. 끝나지 않는 정비창은 알림을 영원히 지우므로 상한을 강제한다."""
    if not isinstance(body, dict):
        raise ConfigError("요청 본문이 객체가 아닙니다")
    starts = parse_dt(body.get("starts_at")) or now
    ends = parse_dt(body.get("ends_at"))
    if ends is None:
        raise ConfigError("ends_at이 필요합니다 (ISO8601)")
    if ends <= starts:
        raise ConfigError("ends_at은 starts_at보다 뒤여야 합니다")
    if ends - starts > timedelta(days=MAX_SILENCE_DAYS):
        raise ConfigError(f"정비창은 최대 {MAX_SILENCE_DAYS}일까지입니다")
    if ends <= now:
        raise ConfigError("이미 끝난 구간은 등록할 수 없습니다")
    return Silence(
        starts_at=starts, ends_at=ends,
        customer_id=str(body.get("customer_id", "") or "").strip(),
        resource_type=str(body.get("resource_type", "") or "").strip(),
        reason=str(body.get("reason", "") or "").strip()[:200],
    )


# ────────────────────────────────── 유일한 IO (인제스터·그룹 워커 공유)

_cache: dict = {"at": None, "policy": None}
_monotonic = time.monotonic      # 테스트에서 시계를 바꿔 끼우기 위한 간접 참조


def reset_cache() -> None:
    _cache["at"] = None
    _cache["policy"] = None


def load(table, base: SuppressionPolicy) -> tuple[SuppressionPolicy, bool]:
    """DB에서 정책 + 정비창을 읽어 기준 정책 위에 얹는다. (정책, 읽기 성공 여부).

    실패해도 기준 정책(환경변수)으로 계속 동작한다 — 설정 저장소가 흔들려도 정제는 돌아야 한다.
    다만 그때 정비창은 비어 있으므로 억제가 **덜** 되지 실수로 더 되지는 않는다.
    """
    try:
        policy_item = table.get_item(
            Key={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT}).get("Item")
        silence_items: list[dict] = []
        kwargs: dict = {"KeyConditionExpression": Key("config_type").eq(CONFIG_SILENCE)}
        while True:
            resp = table.query(**kwargs)
            silence_items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except ClientError as e:
        logger.error("alert config load failed — using env defaults, no silences: %s", e)
        return base, False

    policy = policy_from_item(base, policy_item)
    return (
        SuppressionPolicy(
            auto_pause_sec=policy.auto_pause_sec,
            repeat_interval_sec=policy.repeat_interval_sec,
            exempt_severities=policy.exempt_severities,
            flapping_window_days=policy.flapping_window_days,
            flapping_per_day=policy.flapping_per_day,
            flapping_quarantine_sec=policy.flapping_quarantine_sec,
            group_wait_sec=policy.group_wait_sec,
            silences=silences_from_items(silence_items),
        ),
        True,
    )


def load_cached(table, base: SuppressionPolicy) -> tuple[SuppressionPolicy, bool]:
    """`load()`에 TTL 캐시를 씌운 것. 테이블이 없으면 기준 정책을 그대로 쓴다."""
    if table is None:
        return base, True                      # 설정 저장소 미구성 — 환경변수 모드(결함 아님)
    now = _monotonic()
    at = _cache["at"]
    if at is not None and now - at < CONFIG_CACHE_TTL_SEC and _cache["policy"] is not None:
        return _cache["policy"], True
    policy, ok = load(table, base)
    if ok:
        _cache["at"], _cache["policy"] = now, policy
    return policy, ok
