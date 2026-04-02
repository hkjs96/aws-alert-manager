"""
SQSCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 SQS 큐 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/SQS, 디멘션: QueueName.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_sqs_client():
    """SQS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sqs")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 SQS 큐 목록 반환.

    list_queues() paginator로 전체 큐 URL 조회 후
    list_queue_tags()로 태그 확인, Monitoring=on 필터링.
    id는 URL에서 마지막 '/' 이후 부분(queue_name) 추출.
    """
    try:
        client = _get_sqs_client()
        paginator = client.get_paginator("list_queues")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("SQS list_queues failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for url in page.get("QueueUrls", []):
            tags = _get_queue_tags(client, url)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            queue_name = url.rsplit("/", 1)[-1]
            resources.append(
                ResourceInfo(
                    id=queue_name,
                    type="SQS",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 SQS 큐 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/SQS):
    - ApproximateNumberOfMessagesVisible (Average) → 'SQSMessagesVisible'
    - ApproximateAgeOfOldestMessage (Maximum) → 'SQSOldestMessage'
    - NumberOfMessagesSent (Sum) → 'SQSMessagesSent'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "QueueName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/SQS", "ApproximateNumberOfMessagesVisible", dim,
                    start_time, end_time, "SQSMessagesVisible", metrics, CW_STAT_AVG)
    _collect_metric("AWS/SQS", "ApproximateAgeOfOldestMessage", dim,
                    start_time, end_time, "SQSOldestMessage", metrics, "Maximum")
    _collect_metric("AWS/SQS", "NumberOfMessagesSent", dim,
                    start_time, end_time, "SQSMessagesSent", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """SQS 큐 존재 여부 확인."""
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for SQS %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_queue_tags(sqs_client, queue_url: str) -> dict:
    """SQS list_queue_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    try:
        response = sqs_client.list_queue_tags(QueueUrl=queue_url)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("SQS list_queue_tags failed for %s: %s", queue_url, e)
        return {}
