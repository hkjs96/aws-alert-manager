"""
Alert Ingestor — 알람 이벤트 수집 진입점 (docs/specs/alert-pipeline/ Phase 1.3)

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
"""

import functools
import json
import logging
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from boto3.dynamodb.conditions import Key

from common.alarm_registry import get_severity
from common.alert_event import from_eventbridge, to_item
from common.alert_suppression import DEFER, NOTIFY, SuppressionPolicy, decide
from common.perf_log import log_perf

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_ddb():
    """DynamoDB 리소스 싱글턴 (AGENTS.md AP-7)."""
    return boto3.resource("dynamodb")


@functools.lru_cache(maxsize=1)
def _account_to_customer() -> dict[str, str]:
    """계정 ID → 고객사 ID 매핑.

    이벤트에는 고객사 정보가 없으므로 계정으로 역참조한다. 컨테이너 수명 동안 캐시한다 —
    계정 등록은 드물고, 놓쳐도 다음 콜드 스타트에 반영된다. 매핑이 없으면 빈 문자열로
    남기고 이벤트는 그대로 적재한다(고객사 미지정 이벤트가 유실되면 안 된다).
    """
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
        logger.error("Account→customer mapping lookup failed: %s", e)
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
    repeat = os.environ.get("ALERT_REPEAT_INTERVAL_SEC", "")
    kwargs = {"auto_pause_sec": pause}
    if repeat.isdigit():
        kwargs["repeat_interval_sec"] = int(repeat)
    return SuppressionPolicy(**kwargs)


def _last_notified_at(table, series_id: str):
    """같은 지문으로 마지막으로 '보낸' 시각. 중복 판정(R3-1)의 입력.

    최근 항목만 역순으로 훑는다 — 전체를 읽으면 오래된 알람일수록 비싸진다.
    조회 실패는 억제하지 않는 쪽으로 흘려보낸다(알림을 잃는 것보다 중복이 낫다).
    """
    try:
        resp = table.query(
            KeyConditionExpression=Key("series_id").eq(series_id),
            ScanIndexForward=False, Limit=20,
        )
    except ClientError as e:
        logger.warning("last-notified lookup failed for %s: %s", series_id, e)
        return None
    for item in resp.get("Items", []):
        if not item.get("suppressed", True) and item.get("occurred_at"):
            try:
                return datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


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

    table = _get_ddb().Table(table_name)
    decision = decide(
        alert,
        policy=_policy(),
        last_notified_at=_last_notified_at(table, alert.series_id),
        # 벽시계가 아니라 이벤트 발생 시각으로 판정한다 — 재시도로 늦게 처리돼도
        # 중복·정비창 판정이 흔들리지 않고, 과거 이벤트 재현도 같은 결과가 나온다.
        now=alert.occurred_dt,
    )
    # Shadow: 판정을 기록만 한다. DEFER는 타이머(Step Functions, tasks 1.4.2)가 붙기 전까지
    # 실행할 수 없으므로 억제로 세지 않는다 — 세면 억제율이 과대 집계된다.
    alert.suppressed = decision.action not in (NOTIFY, DEFER)
    alert.suppression_reason = decision.reason

    table.put_item(Item=to_item(alert))

    log_perf(
        "alert_ingest", 0,
        event_type=alert.event_type,
        state=alert.state or "-",
        resource_type=alert.resource_type or "-",
        severity=alert.severity or "-",
        action=decision.action,
        reason=decision.reason or "-",
        parsed=not alert.parse_error,
    )
    logger.info(
        "Ingested %s: alarm=%s state=%s verdict=%s(%s) series=%s%s",
        alert.event_type, alert.alarm_name, alert.state,
        decision.action, decision.reason or "-", alert.series_id,
        f" (parse_error={alert.parse_error})" if alert.parse_error else "",
    )
    return {
        "status": "ok",
        "event_id": alert.event_id,
        "series_id": alert.series_id,
        "action": decision.action,
        "reason": decision.reason,
        "suppressed": alert.suppressed,
    }
