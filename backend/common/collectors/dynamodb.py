"""
DynamoDB 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 테이블 이름(ARN `table/<name>`의 마지막 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/dynamodb.py`)의
알람 정의에서 만든다. 네임스페이스 AWS/DynamoDB, 디멘션 TableName.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.dynamodb import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_dynamodb_client():
    """DynamoDB 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("dynamodb")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_tables → 테이블마다 describe_table(ARN) + list_tags_of_resource(2N+1). (table_name, tags)."""
    try:
        client = _get_dynamodb_client()
        paginator = client.get_paginator("list_tables")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("DynamoDB list_tables failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for table_name in page.get("TableNames", []):
            arn = _get_table_arn(client, table_name)
            if not arn:
                continue
            found.append((table_name, _get_tags(client, arn)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """DynamoDB 테이블 존재 여부 확인 — describe_table."""
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
    cached = cached_tags(resource_arn)
    if cached is not None:
        return cached
    try:
        response = dynamodb_client.list_tags_of_resource(ResourceArn=resource_arn)
        return {t["Key"]: t["Value"] for t in response.get("Tags", [])}
    except ClientError as e:
        logger.error("DynamoDB list_tags_of_resource failed for %s: %s", resource_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
