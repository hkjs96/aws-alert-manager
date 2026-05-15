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


def resource_inventory_table():
    return _get_dynamodb().Table(os.environ["RESOURCE_INVENTORY_TABLE"])


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
