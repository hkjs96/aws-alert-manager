"""
SNSCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 SNS 토픽 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/SNS, 디멘션: TopicName.
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
def _get_sns_client():
    """SNS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sns")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 SNS 토픽 목록 반환.

    list_topics() paginator로 전체 토픽 ARN 조회 후
    list_tags_for_resource()로 태그 확인, Monitoring=on 필터링.
    id는 ARN에서 마지막 ':' 이후 부분(topic_name) 추출.
    """
    try:
        client = _get_sns_client()
        paginator = client.get_paginator("list_topics")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("SNS list_topics failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for topic in page.get("Topics", []):
            topic_arn = topic["TopicArn"]
            tags = _get_tags(client, topic_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            topic_name = topic_arn.rsplit(":", 1)[-1]
            resources.append(
                ResourceInfo(
                    id=topic_name,
                    type="SNS",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 SNS 토픽 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/SNS):
    - NumberOfNotificationsFailed (Sum) → 'SNSNotificationsFailed'
    - NumberOfMessagesPublished (Sum) → 'SNSMessagesPublished'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "TopicName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/SNS", "NumberOfNotificationsFailed", dim,
                    start_time, end_time, "SNSNotificationsFailed", metrics, CW_STAT_SUM)
    _collect_metric("AWS/SNS", "NumberOfMessagesPublished", dim,
                    start_time, end_time, "SNSMessagesPublished", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """SNS 토픽 존재 여부 확인. ARN 재구성 필요."""
    client = _get_sns_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            # topic name에서 ARN 재구성
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for SNS %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(sns_client, topic_arn: str) -> dict:
    """SNS list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환."""
    try:
        response = sns_client.list_tags_for_resource(ResourceArn=topic_arn)
        return {t["Key"]: t["Value"] for t in response.get("Tags", [])}
    except ClientError as e:
        logger.error("SNS list_tags_for_resource failed for %s: %s", topic_arn, e)
        return {}
