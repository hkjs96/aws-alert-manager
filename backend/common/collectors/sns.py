"""
SNS 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 토픽 이름(ARN의 마지막 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/sns.py`)의 알람 정의에서 만든다.
네임스페이스 AWS/SNS, 디멘션 TopicName.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.sns import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_sns_client():
    """SNS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sns")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_topics 후 토픽마다 list_tags_for_resource(N+1). (topic_name, tags)."""
    try:
        client = _get_sns_client()
        paginator = client.get_paginator("list_topics")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("SNS list_topics failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for topic in page.get("Topics", []):
            topic_arn = topic["TopicArn"]
            found.append((topic_arn.rsplit(":", 1)[-1], _get_tags(client, topic_arn)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """SNS 토픽 존재 여부 확인. ARN 재구성 필요."""
    client = _get_sns_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            sts = boto3.client("sts")
            account_id = sts.get_caller_identity()["Account"]
            region = boto3.session.Session().region_name or "us-east-1"
            topic_arn = f"arn:aws:sns:{region}:{account_id}:{name}"
            client.get_topic_attributes(TopicArn=topic_arn)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NotFound":
                logger.info("SNS topic not found (orphan): %s", name)
            else:
                logger.error("get_topic_attributes failed for %s: %s", name, e)
    return alive


def _get_tags(sns_client, topic_arn: str) -> dict:
    """SNS list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환."""
    cached = cached_tags(topic_arn)
    if cached is not None:
        return cached
    try:
        response = sns_client.list_tags_for_resource(ResourceArn=topic_arn)
        return {t["Key"]: t["Value"] for t in response.get("Tags", [])}
    except ClientError as e:
        logger.error("SNS list_tags_for_resource failed for %s: %s", topic_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
