"""
CLBCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 Classic Load Balancer 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/ELB, 디멘션: LoadBalancerName.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import (
    query_metric,
    CW_LOOKBACK_MINUTES,
    CW_STAT_AVG,
    CW_STAT_SUM,
)

logger = logging.getLogger(__name__)

CW_STAT_MAX = "Maximum"


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_elb_client():
    """Classic ELB 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elb")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 Classic Load Balancer 목록 반환.

    describe_load_balancers() paginator로 전체 CLB 조회 후
    describe_tags()로 태그 확인, Monitoring=on 필터링.
    """
    try:
        client = _get_elb_client()
        paginator = client.get_paginator("describe_load_balancers")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("ELB describe_load_balancers failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for lb in page.get("LoadBalancerDescriptions", []):
            lb_name = lb["LoadBalancerName"]

            tags = _get_tags(client, lb_name)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=lb_name,
                    type="CLB",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 CLB 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/ELB):
    - UnHealthyHostCount (Average) → 'CLBUnHealthyHost'
    - HTTPCode_ELB_5XX (Sum) → 'CLB5XX'
    - HTTPCode_ELB_4XX (Sum) → 'CLB4XX'
    - HTTPCode_Backend_5XX (Sum) → 'CLBBackend5XX'
    - HTTPCode_Backend_4XX (Sum) → 'CLBBackend4XX'
    - SurgeQueueLength (Maximum) → 'SurgeQueueLength'
    - SpilloverCount (Sum) → 'SpilloverCount'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "LoadBalancerName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/ELB", "UnHealthyHostCount", dim,
                    start_time, end_time, "CLBUnHealthyHost", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ELB", "HTTPCode_ELB_5XX", dim,
                    start_time, end_time, "CLB5XX", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ELB", "HTTPCode_ELB_4XX", dim,
                    start_time, end_time, "CLB4XX", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ELB", "HTTPCode_Backend_5XX", dim,
                    start_time, end_time, "CLBBackend5XX", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ELB", "HTTPCode_Backend_4XX", dim,
                    start_time, end_time, "CLBBackend4XX", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ELB", "SurgeQueueLength", dim,
                    start_time, end_time, "SurgeQueueLength", metrics, CW_STAT_MAX)
    _collect_metric("AWS/ELB", "SpilloverCount", dim,
                    start_time, end_time, "SpilloverCount", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """Classic Load Balancer 존재 여부 확인."""
    client = _get_elb_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.describe_load_balancers(LoadBalancerNames=[name])
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("LoadBalancerNotFound", "AccessPointNotFound"):
                logger.info("CLB not found (orphan): %s", name)
            else:
                logger.error("describe_load_balancers failed for %s: %s", name, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for CLB %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(elb_client, lb_name: str) -> dict:
    """Classic ELB describe_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not lb_name:
        return {}
    try:
        response = elb_client.describe_tags(LoadBalancerNames=[lb_name])
        descriptions = response.get("TagDescriptions", [])
        if not descriptions:
            return {}
        return {t["Key"]: t["Value"] for t in descriptions[0].get("Tags", [])}
    except ClientError as e:
        logger.error("ELB describe_tags failed for %s: %s", lb_name, e)
        return {}
