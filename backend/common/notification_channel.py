"""
알림 채널 — 고객사별 채널 정의와 조건 매칭 (tasks 2.2.1~2.2.3, design.md D3)

    NotificationChannelTable   PK customer_id / SK channel_id
      customer_id = ""  →  **전역 채널**(모든 고객사의 알림을 받는다, 우리 관제 채널용)

알람에 수신처를 박지 않는다. 채널은 표의 행이고 라우터가 조회한다 — 채널을 더해도 알람을
고치지 않고(R6-5), 알람당 액션 5개 제한에도 걸리지 않는다.

**고객사는 조건이 아니라 키다.** 조건(match)은 한 고객사 **안에서만** 범위를 좁힌다. 이렇게
나눠야 조건 처리에 버그가 생겨도 A사 알림이 B사 채널로 새지 않는다 — 조건이 넓게 해석되면
소음이 늘 뿐이고, 경계는 키가 지킨다.

조건은 필드마다 **목록**이며 비어 있으면 "전부"다. 나중에 축을 더해도(예: 시간대) 기존 행은
그 필드가 없으니 그대로 "전부"로 동작한다 — 마이그레이션이 필요 없다.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from common.notification_adapters import (
    REDACTED,
    SEVERITY_ORDER,
    Adapter,
    AdapterError,
    Notification,
    get as get_adapter,
)

#: 조건에 쓸 수 있는 축. 여기에 이름을 더하고 이벤트에서 같은 이름을 읽을 수 있으면 축이 늘어난다.
MATCH_FIELDS: tuple[str, ...] = ("severity", "resource_type", "account_id")

#: 전역 채널이 표에서 사는 파티션 키. **DynamoDB는 키 속성에 빈 문자열을 허용하지 않는다**
#: (라이브에서 드러났다 — 가짜 테이블은 이 제약을 흉내 내지 않아 단위 테스트가 통과했다).
#: 도메인에서는 계속 `customer_id == ""`가 전역이고, 이 변환은 저장 경계에서만 일어난다.
GLOBAL_KEY = "__global__"

#: 한 고객사가 가질 수 있는 채널 수 — 폭주한 설정이 발송을 마비시키지 않게.
MAX_CHANNELS_PER_CUSTOMER = 50
MAX_NAME_LEN = 60
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChannelError(ValueError):
    """채널 정의가 잘못됐다 — API가 400으로 돌려준다."""


@dataclass(frozen=True)
class Channel:
    channel_id: str
    customer_id: str          # "" = 전역
    name: str
    type: str
    config: dict = field(default_factory=dict)
    match: dict = field(default_factory=dict)
    enabled: bool = True

    @property
    def adapter(self) -> Adapter:
        return get_adapter(self.type)

    @property
    def is_global(self) -> bool:
        return not self.customer_id


def new_channel_id() -> str:
    return uuid.uuid4().hex[:16]


def storage_key(customer_id: str) -> str:
    """도메인의 고객사 ID → 표의 파티션 키. 전역("")은 센티넬로 저장한다."""
    return str(customer_id or "") or GLOBAL_KEY


def customer_from_storage_key(key: str) -> str:
    """표의 파티션 키 → 도메인의 고객사 ID."""
    key = str(key or "")
    return "" if key == GLOBAL_KEY else key


# ────────────────────────────────── 검증 (API 입력 → Channel)

def _clean_list(raw, field_name: str) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        raise ChannelError(f"{field_name} 조건은 목록이어야 합니다")
    out: list[str] = []
    for v in raw:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def validate_match(raw) -> dict:
    """조건 검증. **모르는 축은 거절한다.**

    조용히 버리면 사용자는 "RDS만"이라고 저장했다고 믿는데 실제로는 전부 받는다.
    이걸 막아야 저장된 행에는 아는 축만 남고, 라우터가 모르는 축을 만날 일이 없다.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ChannelError("match는 객체여야 합니다")
    unknown = sorted(set(raw) - set(MATCH_FIELDS))
    if unknown:
        raise ChannelError(
            f"조건으로 쓸 수 없는 항목입니다: {', '.join(unknown)} "
            f"(가능: {', '.join(MATCH_FIELDS)})")
    out: dict = {}
    for name in MATCH_FIELDS:
        values = _clean_list(raw.get(name), name)
        if not values:
            continue
        if name == "severity":
            bad = [v for v in values if v not in SEVERITY_ORDER]
            if bad:
                raise ChannelError(f"등급은 {', '.join(SEVERITY_ORDER)} 중에서 고릅니다: {', '.join(bad)}")
        out[name] = values
    return out


def _keep_existing_secrets(config: dict, adapter: Adapter, existing: Channel | None) -> dict:
    """수정 시 자격증명을 다시 받지 않아도 되게, 빠졌거나 가림 문자열이면 저장된 값을 쓴다.

    화면은 자격증명 자리에 `REDACTED`만 보여 준다(값을 모른다). 그걸 그대로 돌려보냈다고 해서
    웹훅 URL을 지워 버리면, 사용자는 이름만 고쳤는데 발송이 조용히 멈춘다.
    """
    if existing is None:
        return config
    merged = dict(config)
    for name in adapter.secret_fields:
        supplied = str(merged.get(name, "") or "").strip()
        if (not supplied or supplied == REDACTED) and name in existing.config:
            merged[name] = existing.config[name]
    return merged


def validate_channel(body: dict, *, customer_id: str, existing: "Channel | None" = None) -> Channel:
    """API 입력 → Channel. 자격증명 형식까지 어댑터 선언을 따라 검사한다.

    `existing`을 주면 수정으로 본다 — 자격증명을 다시 안 보내도 저장된 값이 유지된다.
    """
    if not isinstance(body, dict):
        raise ChannelError("요청 본문이 객체가 아닙니다")

    name = str(body.get("name", "") or "").strip()
    if not name:
        raise ChannelError("채널 이름이 필요합니다")
    if len(name) > MAX_NAME_LEN:
        raise ChannelError(f"채널 이름은 {MAX_NAME_LEN}자를 넘을 수 없습니다")

    try:
        adapter = get_adapter(body.get("type", "") or (existing.type if existing else ""))
        raw_config = dict(body.get("config") or {})
        # 가림 문자열은 "안 바꿈"이라는 뜻이다 — 형식 검사에 넣으면 항상 실패한다.
        for secret in adapter.secret_fields:
            if str(raw_config.get(secret, "") or "").strip() == REDACTED:
                raw_config.pop(secret, None)
        config = adapter.validate_config(
            _keep_existing_secrets(raw_config, adapter, existing))
    except AdapterError as e:
        raise ChannelError(str(e)) from None

    if str(customer_id or "").strip() == GLOBAL_KEY:
        # 센티넬을 고객사 ID로 쓰면 전역 채널로 위장할 수 있다.
        raise ChannelError(f"{GLOBAL_KEY}는 고객사 ID로 쓸 수 없습니다")

    channel_id = str(body.get("channel_id", "") or "").strip() or new_channel_id()
    if not _ID_RE.match(channel_id):
        raise ChannelError("channel_id 형식이 올바르지 않습니다")

    return Channel(
        channel_id=channel_id,
        customer_id=str(customer_id or "").strip(),
        name=name,
        type=adapter.type,
        config=config,
        match=validate_match(body.get("match")),
        enabled=bool(body.get("enabled", True)),
    )


# ────────────────────────────────── 저장소 표현

def channel_to_item(ch: Channel, *, created_by: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "customer_id": storage_key(ch.customer_id),
        "channel_id": ch.channel_id,
        "name": ch.name,
        "type": ch.type,
        "config": dict(ch.config),
        "match": dict(ch.match),
        "enabled": ch.enabled,
        "updated_at": now.isoformat(),
        "updated_by": created_by,
    }


def channel_from_item(item: dict) -> Channel:
    return Channel(
        channel_id=str(item.get("channel_id", "")),
        customer_id=customer_from_storage_key(item.get("customer_id", "")),
        name=str(item.get("name", "")),
        type=str(item.get("type", "")),
        config=dict(item.get("config") or {}),
        match=dict(item.get("match") or {}),
        enabled=bool(item.get("enabled", True)),
    )


def channel_to_dict(ch: Channel) -> dict:
    """API 응답용. **자격증명 값은 절대 나가지 않는다** — 어댑터 선언이 그걸 정한다(R6-8)."""
    return {
        "channel_id": ch.channel_id,
        "customer_id": ch.customer_id,
        "name": ch.name,
        "type": ch.type,
        "type_label": ch.adapter.label,
        "config": ch.adapter.public_config(ch.config),
        "match": dict(ch.match),
        "enabled": ch.enabled,
        "is_global": ch.is_global,
    }


# ────────────────────────────────── 조건 매칭

def matches(ch: Channel, event: dict) -> bool:
    """이 채널이 이 이벤트를 받아야 하는가.

    고객사 경계는 여기서 보지 않는다 — 조회가 키로 이미 나눴다(전역 채널은 모두를 받는다).
    각 축은 비어 있으면 "전부"이고, 값이 있으면 그중 하나와 같아야 한다.

    이벤트 쪽 값이 **목록**이면(사건 재알림 — 여러 알람을 묶었다) 그중 하나라도 허용 목록에 있으면
    통과다. 빈 목록은 빈 값과 같다 — 좁힌 축은 통과하지 못한다.
    """
    if not ch.enabled:
        return False
    for name, allowed in ch.match.items():
        if name not in MATCH_FIELDS:
            continue          # 저장 시 걸러지지만, 옛 행이 남아도 좁히지 못할 뿐 새지는 않는다
        if not allowed:
            continue
        value = event.get(name, "")
        if isinstance(value, (list, tuple, set)):
            if not any(str(v) in allowed for v in value if v):
                return False
        elif str(value or "") not in allowed:
            return False
    return True


def select(channels: list[Channel], event: dict) -> list[Channel]:
    """이벤트를 받을 채널 목록. 순서는 안정적이다(전역 뒤, 이름순)."""
    hit = [c for c in channels if matches(c, event)]
    return sorted(hit, key=lambda c: (c.is_global, c.name, c.channel_id))


def notification_from_event(event: dict, *, url: str = "", count: int = 1,
                           incident_id: str = "") -> Notification:
    """이력 항목/이벤트 → 어댑터가 그릴 알림. 어댑터가 이벤트를 파싱하지 않게 여기서 한 번만 한다."""
    return Notification(
        title=str(event.get("alarm_name", "") or event.get("title", "") or "알람"),
        severity=str(event.get("severity", "") or ""),
        customer_id=str(event.get("customer_id", "") or ""),
        account_id=str(event.get("account_id", "") or ""),
        resource_id=str(event.get("resource_id", "") or ""),
        resource_type=str(event.get("resource_type", "") or ""),
        metric_key=str(event.get("metric_key", "") or ""),
        state=str(event.get("state", "") or ""),
        reason=str(event.get("state_reason", "") or ""),
        occurred_at=str(event.get("occurred_at", "") or ""),
        url=url,
        count=max(1, int(count or 1)),
        incident_id=incident_id,
    )
