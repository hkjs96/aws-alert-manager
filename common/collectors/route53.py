"""
Route53Collector - Extended Resource Monitoring

Monitoring=on 태그가 있는 Route53 Health Check 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/Route53, 디멘션: HealthCheckId.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_route53_client():
    """Route53 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("route53")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 Route53 Health Check 목록 반환.

    list_health_checks() paginator로 전체 Health Check 조회 후
    list_tags_for_resource(ResourceType='healthcheck')로 태그 확인.
    """
    try:
        client = _get_route53_client()
        paginator = client.get_paginator("list_health_checks")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Route53 list_health_checks failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for hc in page.get("HealthChecks", []):
            hc_id = hc["Id"]
            tags = _get_tags(client, hc_id)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=hc_id,
                    type="Route53",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 Route53 Health Check 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/Route53, us-east-1 고정):
    - HealthCheckStatus (Minimum) → 'HealthCheckStatus'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "HealthCheckId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/Route53", "HealthCheckStatus", dim,
                    start_time, end_time, "HealthCheckStatus", metrics, "Minimum")

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """Route53 Health Check 존재 여부 확인."""
    client = _get_route53_client()
    alive: set[str] = set()
    for hc_id in tag_names:
        try:
            client.get_health_check(HealthCheckId=hc_id)
            alive.add(hc_id)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchHealthCheck":
                logger.info("Route53 health check not found (orphan): %s", hc_id)
            else:
                logger.error("get_health_check failed for %s: %s", hc_id, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for Route53 %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(route53_client, health_check_id: str) -> dict:
    """Route53 list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환."""
    try:
        response = route53_client.list_tags_for_resource(
            ResourceType="healthcheck", ResourceId=health_check_id)
        tag_set = response.get("ResourceTagSet", {})
        return {t["Key"]: t["Value"] for t in tag_set.get("Tags", [])}
    except ClientError as e:
        logger.error("Route53 list_tags_for_resource failed for %s: %s",
                     health_check_id, e)
        return {}
