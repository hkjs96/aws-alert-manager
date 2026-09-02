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
"""

import functools
import logging
import os

import boto3
from botocore.exceptions import ClientError

from common.alert_event import from_eventbridge, to_item
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


def lambda_handler(event, context):
    """EventBridge 이벤트 1건을 정규화해 적재한다."""
    table_name = os.environ.get("EVENT_HISTORY_TABLE", "")
    if not table_name:
        logger.error("EVENT_HISTORY_TABLE is not configured — event dropped: %s",
                     (event or {}).get("id", ""))
        return {"status": "skipped", "reason": "no_table"}

    customer_id = _account_to_customer().get(str((event or {}).get("account", "")), "")
    alert = from_eventbridge(event, customer_id=customer_id)
    item = to_item(alert)

    _get_ddb().Table(table_name).put_item(Item=item)

    log_perf(
        "alert_ingest", 0,
        event_type=alert.event_type,
        state=alert.state or "-",
        resource_type=alert.resource_type or "-",
        parsed=not alert.parse_error,
    )
    logger.info(
        "Ingested %s: alarm=%s state=%s series=%s%s",
        alert.event_type, alert.alarm_name, alert.state, alert.series_id,
        f" (parse_error={alert.parse_error})" if alert.parse_error else "",
    )
    return {
        "status": "ok",
        "event_id": alert.event_id,
        "series_id": alert.series_id,
        "suppressed": alert.suppressed,
    }
