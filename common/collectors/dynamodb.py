"""
DynamoDBCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 DynamoDB 테이블 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/DynamoDB, 디멘션: TableName.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_dynamodb_client():
    """DynamoDB 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("dynamodb")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 DynamoDB 테이블 목록 반환.

    list_tables() paginator로 전체 테이블 조회 후
    describe_table()로 ARN 획득, list_tags_of_resource()로 태그 확인.
    """
    try:
        client = _get_dynamodb_client()
        paginator = client.get_paginator("list_tables")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("DynamoDB list_tables failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for table_name in page.get("TableNames", []):
            arn = _get_table_arn(client, table_name)
            if not arn:
                continue

            tags = _get_tags(client, arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=table_name,
                    type="DynamoDB",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 DynamoDB 테이블 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/DynamoDB):
    - ConsumedReadCapacityUnits (Sum) → 'DDBReadCapacity'
    - ConsumedWriteCapacityUnits (Sum) → 'DDBWriteCapacity'
    - ThrottledRequests (Sum) → 'ThrottledRequests'
    - SystemErrors (Sum) → 'DDBSystemErrors'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "TableName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/DynamoDB", "ConsumedReadCapacityUnits", dim,
                    start_time, end_time, "DDBReadCapacity", metrics, CW_STAT_SUM)
    _collect_metric("AWS/DynamoDB", "ConsumedWriteCapacityUnits", dim,
                    start_time, end_time, "DDBWriteCapacity", metrics, CW_STAT_SUM)
    _collect_metric("AWS/DynamoDB", "ThrottledRequests", dim,
                    start_time, end_time, "ThrottledRequests", metrics, CW_STAT_SUM)
    _collect_metric("AWS/DynamoDB", "SystemErrors", dim,
                    start_time, end_time, "DDBSystemErrors", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """DynamoDB 테이블 존재 여부 확인."""
    client = _get_dynamodb_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.describe_table(TableName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("DynamoDB table not found (orphan): %s", name)
            else:
                logger.error("describe_table failed for %s: %s", name, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for DynamoDB %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_table_arn(dynamodb_client, table_name: str) -> str | None:
    """describe_table로 ARN 조회. ClientError 시 None 반환."""
    try:
        response = dynamodb_client.describe_table(TableName=table_name)
        return response["Table"]["TableArn"]
    except ClientError as e:
        logger.error("DynamoDB describe_table failed for %s: %s", table_name, e)
        return None


def _get_tags(dynamodb_client, resource_arn: str) -> dict:
    """DynamoDB list_tags_of_resource 래퍼. ClientError 시 빈 dict 반환."""
    try:
        response = dynamodb_client.list_tags_of_resource(ResourceArn=resource_arn)
        return {t["Key"]: t["Value"] for t in response.get("Tags", [])}
    except ClientError as e:
        logger.error("DynamoDB list_tags_of_resource failed for %s: %s", resource_arn, e)
        return {}
