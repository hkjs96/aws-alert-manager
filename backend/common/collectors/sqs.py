"""
SQS 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 큐 이름(URL·ARN의 마지막 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/sqs.py`)의 알람 정의에서 만든다.
네임스페이스 AWS/SQS, 디멘션 QueueName.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.sqs import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_sqs_client():
    """SQS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sqs")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_queues 후 큐마다 list_queue_tags(N+1). (queue_name, tags)."""
    try:
        client = _get_sqs_client()
        paginator = client.get_paginator("list_queues")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("SQS list_queues failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for url in page.get("QueueUrls", []):
            found.append((url.rsplit("/", 1)[-1], _get_queue_tags(client, url)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """SQS 큐 존재 여부 확인 — get_queue_url."""
    client = _get_sqs_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.get_queue_url(QueueName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "AWS.SimpleQueueService.NonExistentQueue":
                logger.info("SQS queue not found (orphan): %s", name)
            else:
                logger.error("get_queue_url failed for %s: %s", name, e)
    return alive


def _get_queue_tags(sqs_client, queue_url: str) -> dict:
    """SQS list_queue_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    try:
        response = sqs_client.list_queue_tags(QueueUrl=queue_url)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("SQS list_queue_tags failed for %s: %s", queue_url, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
