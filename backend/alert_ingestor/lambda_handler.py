"""
Alert Ingestor — 알람 이벤트 수집 진입점 (docs/specs/alert-pipeline/ Phase 1.3 / 1.4)

EventBridge가 전달한 CloudWatch 알람 이벤트를 정규화해 EventHistoryTable에 적재한다.
**정제(억제) 이전에 원본 전량을 기록한다** (R2-1) — 이 단계에서 버린 이벤트는 되돌릴 수 없고,
Phase 4 AIOps의 학습 데이터이기도 하다.

수신 경로 2개:
  - 커스텀 버스 `aws-monitoring-alert-{env}` ← 고객사 계정에서 크로스 어카운트 전달
  - 기본 버스 ← 단일 계정 모드(우리 계정 자신의 알람)

이벤트 하나당 한 번 호출된다(EventBridge → Lambda 직접 타깃). 실패 시 EventBridge가
재시도하고, 소진되면 DLQ로 간다 — 여기서 예외를 삼키면 그 안전망이 무력해지므로
**적재 실패는 예외를 그대로 올린다.** 반대로 파싱 실패는 예외가 아니다(알 수 없는 형태도 기록 대상).

**정제는 지금 Shadow 모드다.** `alert_suppression.decide()`의 판정을 항목에 기록만 하고
아무것도 막지 않는다 — 알림 발송자(Phase 2.2)가 아직 없기 때문이다. 덕분에 발송을 붙이기 전에
실제 트래픽으로 억제율(R9-1)을 측정하고 규칙을 검증할 수 있다. 임계치 재보정과 같은 방식이다.

**판정 재료는 상태 테이블에서 온다(design.md D9).** 순서는 **상태 먼저, 이력 나중**:
  1. `fp#{지문}` 읽기 → `decide()` → 새 상태를 **조건부**(version)로 쓴다
  2. 이력 적재
반대로 하면 이력을 쓴 뒤 크래시 → 재시도 → 이력은 이미 있음 → 상태가 영영 갱신되지 않는다.
상태 갱신은 멱등이라(같은 이벤트 두 번 = 한 번) 재시도에 안전하고, 이력 put은 같은 키를 덮어쓴다.
조건 충돌은 같은 지문의 이벤트가 동시에 처리됐다는 뜻이다 — 다시 읽어 재판정하면 진 쪽은
`last_notified_at`을 보고 dedup이 된다. 이게 이중 발송을 막는 유일한 지점이다(Phase 2 claim-then-send).

**상태 조회·갱신 실패는 fail-open이다** — 알림을 잃는 것보다 중복이 낫다. 단, 이 원칙은
IAM 누락 같은 결함을 숨긴다(2026-09-07 실측: Query 권한 누락으로 dedup이 조용히 죽어 있었다).
그래서 실패는 ERROR 로그 + `PERF_METRIC state_ok=false`로 남기고, 배포 뒤 `AccessDenied`를 grep한다.
"""

import functools
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from common.alarm_registry import get_severity
from common.alert_event import STATE_CHANGE, from_eventbridge, to_item
from common.alert_state import (
    apply_event,
    fp_key,
    inputs_from_state,
    state_item,
    unchanged,
)
from common.alert_suppression import (
    DEFER,
    NOTIFY,
    Decision,
    SuppressionPolicy,
    decide,
    fingerprint,
)
from common.perf_log import log_perf

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

#: 조건 충돌 재시도 횟수. 같은 지문이 이 이상 연속 충돌하면 fail-open으로 NOTIFY한다.
STATE_MAX_ATTEMPTS = 3
_REASON_CONTENTION = "state_contention"


@functools.lru_cache(maxsize=None)
def _get_ddb():
    """DynamoDB 리소스 싱글턴 (AGENTS.md AP-7)."""
    return boto3.resource("dynamodb")


#: 계정→고객사 매핑 캐시 수명. 컨테이너는 몇 시간을 살므로 무기한 캐시면 새로 등록한
#: 고객사의 이벤트가 그동안 customer_id 없이 적재돼 리포트에서 보이지 않는다(review-2026-09-07 Q2).
ACCOUNT_CACHE_TTL_SEC = 300
_account_cache: dict = {"at": None, "map": {}}
_monotonic = time.monotonic      # 테스트에서 시계를 바꿔 끼우기 위한 간접 참조


def _reset_account_cache() -> None:
    _account_cache["at"] = None
    _account_cache["map"] = {}


def _account_to_customer() -> dict[str, str]:
    """계정 ID → 고객사 ID 매핑 (TTL 캐시).

    이벤트에는 고객사 정보가 없으므로 계정으로 역참조한다. 매핑이 없으면 빈 문자열로 남기고
    이벤트는 그대로 적재한다(고객사 미지정 이벤트가 유실되면 안 된다).

    스캔이 실패하면 **이전 매핑을 유지**하고 TTL 뒤에 다시 시도한다 — 빈 매핑으로 덮으면
    일시 장애 동안 모든 이벤트가 고객사를 잃고, 이벤트마다 재시도하면 장애 중 부하를 키운다.
    """
    now = _monotonic()
    at = _account_cache["at"]
    if at is not None and now - at < ACCOUNT_CACHE_TTL_SEC:
        return _account_cache["map"]

    table_name = os.environ.get("ACCOUNTS_TABLE", "")
    if not table_name:
        return {}
    mapping: dict[str, str] = {}
    try:
        table = _get_ddb().Table(table_name)
        kwargs: dict = {}
        while True:
            resp = table.scan(**kwargs)
            for item in resp.get("Items", []):
                acc = str(item.get("account_id", ""))
                if acc:
                    mapping[acc] = str(item.get("customer_id", ""))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except ClientError as e:
        logger.error("Account→customer mapping lookup failed, keeping previous mapping: %s", e)
        _account_cache["at"] = now
        return _account_cache["map"]

    _account_cache["at"] = now
    _account_cache["map"] = mapping
    return mapping


@functools.lru_cache(maxsize=1)
def _policy() -> SuppressionPolicy:
    """정제 설정. 지금은 환경변수, 이후 DB로 옮긴다 (R3-9, tasks 1.4.6).

    `ALERT_AUTO_PAUSE_SEC`는 severity별 유예 JSON이며 **기본은 비어 있다** —
    값은 Phase 0 실측("N분 유예 시 억제율")으로 정한다. 비어 있으면 유예하지 않는다.
    """
    raw = os.environ.get("ALERT_AUTO_PAUSE_SEC", "").strip()
    pause: dict[str, int] = {}
    if raw:
        try:
            pause = {str(k): int(v) for k, v in json.loads(raw).items()}
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("ALERT_AUTO_PAUSE_SEC is malformed, ignoring: %s", e)
    kwargs: dict = {"auto_pause_sec": pause}
    repeat = os.environ.get("ALERT_REPEAT_INTERVAL_SEC", "")
    if repeat.isdigit():
        kwargs["repeat_interval_sec"] = int(repeat)
    quarantine = os.environ.get("ALERT_FLAPPING_QUARANTINE_SEC", "")
    if quarantine.isdigit():
        kwargs["flapping_quarantine_sec"] = int(quarantine)
    window = os.environ.get("ALERT_FLAPPING_WINDOW_DAYS", "")
    try:
        if window:
            kwargs["flapping_window_days"] = float(window)
    except ValueError:
        logger.error("ALERT_FLAPPING_WINDOW_DAYS is malformed, ignoring: %r", window)
    return SuppressionPolicy(**kwargs)


def _read_state(table, key: str):
    """(상태 항목 또는 None, 조회 성공 여부). 실패는 fail-open — 첫 발화처럼 판정한다."""
    try:
        resp = table.get_item(Key={"state_key": key}, ConsistentRead=True)
    except ClientError as e:
        logger.error("state read failed for %s — deciding as first occurrence: %s", key, e)
        return None, False
    return resp.get("Item"), True


def _write_state(table, key: str, state: dict, expected_version, wall: datetime):
    """조건부 저장. True=성공, False=조건 충돌(재판정 필요), None=그 외 실패(판정은 유지)."""
    if expected_version is None:
        condition = Attr("state_key").not_exists()
        version = 1
    else:
        condition = Attr("version").eq(int(expected_version))
        version = int(expected_version) + 1
    try:
        table.put_item(Item=state_item(key, state, now=wall, version=version),
                       ConditionExpression=condition)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        logger.error("state write failed for %s — decision kept, state not updated: %s", key, e)
        return None


def _decide_with_state(table, key: str, alert, policy: SuppressionPolicy,
                       now: datetime, wall: datetime) -> tuple[Decision, bool]:
    """상태를 읽어 판정하고 조건부로 갱신한다. (판정, 상태 처리 성공 여부)."""
    if table is None:
        return decide(alert, policy=policy, now=now), False

    for _ in range(STATE_MAX_ATTEMPTS):
        state, read_ok = _read_state(table, key)
        inputs = inputs_from_state(state, alert, now=now, policy=policy)
        decision = decide(
            alert, policy=policy,
            last_notified_at=inputs.last_notified_at,
            is_flapping=inputs.is_flapping,
            already_notified=inputs.already_notified,
            now=now,
        )
        if not read_ok:
            return decision, False
        new_state = apply_event(state, alert, decision, now=now, policy=policy)
        if unchanged(state, new_state):
            return decision, True
        wrote = _write_state(table, key, new_state,
                             state.get("version") if state else None, wall)
        if wrote is None:
            return decision, False
        if wrote:
            return decision, True
        # 조건 충돌: 같은 지문의 이벤트가 방금 처리됐다. 다시 읽어 재판정한다.

    logger.warning("state contention on %s after %d attempts — fail-open NOTIFY",
                   key, STATE_MAX_ATTEMPTS)
    return Decision(NOTIFY, _REASON_CONTENTION), False


def lambda_handler(event, context):
    """EventBridge 이벤트 1건을 정규화해 적재한다."""
    table_name = os.environ.get("EVENT_HISTORY_TABLE", "")
    if not table_name:
        logger.error("EVENT_HISTORY_TABLE is not configured — event dropped: %s",
                     (event or {}).get("id", ""))
        return {"status": "skipped", "reason": "no_table"}

    customer_id = _account_to_customer().get(str((event or {}).get("account", "")), "")
    alert = from_eventbridge(event, customer_id=customer_id)
    # 알람 이벤트에는 태그가 실리지 않는다 — 메트릭 키의 기본 등급을 쓴다.
    alert.severity = get_severity(alert.metric_key) if alert.metric_key else ""

    # 벽시계가 아니라 이벤트 발생 시각으로 판정한다 — 재시도로 늦게 처리돼도
    # 중복·정비창 판정이 흔들리지 않고, 과거 이벤트 재현도 같은 결과가 나온다.
    wall = datetime.now(timezone.utc)
    now = alert.occurred_dt or wall
    policy = _policy()

    if alert.event_type != STATE_CHANGE:
        # 알람 생성/수정/삭제는 상태에 관여하지 않는다 — 읽기·쓰기 모두 건너뛴다
        decision, state_ok = decide(alert, policy=policy, now=now), True
    else:
        state_name = os.environ.get("ALERT_STATE_TABLE", "")
        if not state_name:
            logger.error("ALERT_STATE_TABLE is not configured — no dedup/flapping state")
        state_table = _get_ddb().Table(state_name) if state_name else None
        decision, state_ok = _decide_with_state(
            state_table, fp_key(fingerprint(alert)), alert, policy, now, wall)

    # Shadow: 판정을 기록만 한다. DEFER는 타이머(Step Functions, tasks 1.4.3b)가 붙기 전까지
    # 실행할 수 없으므로 억제로 세지 않는다 — 세면 억제율이 과대 집계된다.
    alert.suppressed = decision.action not in (NOTIFY, DEFER)
    alert.suppression_reason = decision.reason

    _get_ddb().Table(table_name).put_item(Item=to_item(alert))

    log_perf(
        "alert_ingest", 0,
        event_type=alert.event_type,
        state=alert.state or "-",
        resource_type=alert.resource_type or "-",
        severity=alert.severity or "-",
        action=decision.action,
        reason=decision.reason or "-",
        parsed=not alert.parse_error,
        state_ok=state_ok,
    )
    logger.info(
        "Ingested %s: alarm=%s state=%s verdict=%s(%s) series=%s%s%s",
        alert.event_type, alert.alarm_name, alert.state,
        decision.action, decision.reason or "-", alert.series_id,
        "" if state_ok else " (state_ok=false)",
        f" (parse_error={alert.parse_error})" if alert.parse_error else "",
    )
    return {
        "status": "ok",
        "event_id": alert.event_id,
        "series_id": alert.series_id,
        "action": decision.action,
        "reason": decision.reason,
        "suppressed": alert.suppressed,
        "state_ok": state_ok,
    }
