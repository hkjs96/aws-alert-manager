"""
DynamoDB 클라이언트 및 공통 헬퍼.

테이블 이름은 환경변수로 주입:
  CUSTOMERS_TABLE, ACCOUNTS_TABLE, THRESHOLD_OVERRIDES_TABLE, JOB_STATUS_TABLE
"""

import functools
import os

import boto3
from botocore.exceptions import ClientError

import logging

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_dynamodb():
    return boto3.resource("dynamodb")


def customers_table():
    return _get_dynamodb().Table(os.environ["CUSTOMERS_TABLE"])


def accounts_table():
    return _get_dynamodb().Table(os.environ["ACCOUNTS_TABLE"])


def threshold_overrides_table():
    return _get_dynamodb().Table(os.environ["THRESHOLD_OVERRIDES_TABLE"])


def job_status_table():
    return _get_dynamodb().Table(os.environ["JOB_STATUS_TABLE"])


def monitor_run_history_table():
    return _get_dynamodb().Table(os.environ["MONITOR_RUN_HISTORY_TABLE"])


def resource_inventory_table():
    return _get_dynamodb().Table(os.environ["RESOURCE_INVENTORY_TABLE"])


def user_preferences_table():
    return _get_dynamodb().Table(os.environ["USER_PREFERENCES_TABLE"])


def alert_policy_table():
    """알림 정제 정책 + 정비창 (docs/specs/alert-pipeline/ tasks 1.4.4·1.4.6)."""
    return _get_dynamodb().Table(os.environ["ALERT_POLICY_TABLE"])


def notification_channel_table():
    """고객사별 알림 채널 (design-notification-channels.md). 자격증명이 여기 함께 있다 —
    응답에 넣지 않는 책임은 `notification_channel.channel_to_dict()`가 진다(R6-8)."""
    return _get_dynamodb().Table(os.environ["NOTIFICATION_CHANNEL_TABLE"])


def incident_table():
    """인시던트 — 사건 단위 대응과 MTTA/MTTR (requirements R4)."""
    return _get_dynamodb().Table(os.environ["INCIDENT_TABLE"])


def event_history_table():
    """알람 이벤트 이력 — 처리 결과·사유 조회 (review-personas F7)."""
    return _get_dynamodb().Table(os.environ["EVENT_HISTORY_TABLE"])


def alert_state_table():
    """지문·그룹 상태 — 격리 해제 시각 조회용 (design.md D9)."""
    return _get_dynamodb().Table(os.environ["ALERT_STATE_TABLE"])


def scan_all(table) -> list[dict]:
    """페이지네이션 처리한 전체 스캔. 소규모 테이블(고객사/어카운트)용."""
    items = []
    kwargs: dict = {}
    try:
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except ClientError as e:
        logger.error("DynamoDB scan failed: %s", e)
        raise
    return items


def query_by_pk(table, pk_name: str, pk_value: str) -> list[dict]:
    """파티션 키 기준 Query. AccountsTable에서 customer_id로 조회할 때 사용."""
    from boto3.dynamodb.conditions import Key
    try:
        resp = table.query(KeyConditionExpression=Key(pk_name).eq(pk_value))
        return resp.get("Items", [])
    except ClientError as e:
        logger.error("DynamoDB query failed (pk=%s): %s", pk_value, e)
        raise
