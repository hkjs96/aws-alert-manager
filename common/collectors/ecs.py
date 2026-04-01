"""
ECSCollector - Extended Resource Monitoring (Compound Dimension)

Monitoring=on 태그가 있는 ECS 서비스 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/ECS, Compound_Dimension: ClusterName + ServiceName.
ECS 태그는 list_tags_for_resource에서 lowercase key/value 사용.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_ecs_client():
    """ECS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ecs")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 ECS 서비스 목록 반환.

    list_clusters → list_services paginator → describe_services 배치
    → list_tags_for_resource → Monitoring=on 필터링.
    _ecs_launch_type, _cluster_name Internal_Tag 설정.
    """
    client = _get_ecs_client()
    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    try:
        cluster_paginator = client.get_paginator("list_clusters")
        cluster_pages = cluster_paginator.paginate()
    except ClientError as e:
        logger.error("ECS list_clusters failed: %s", e)
        raise

    for cluster_page in cluster_pages:
        for cluster_arn in cluster_page.get("clusterArns", []):
            cluster_name = cluster_arn.rsplit("/", 1)[-1]
            _collect_services_for_cluster(
                client, cluster_arn, cluster_name, region, resources)

    return resources


def _collect_services_for_cluster(client, cluster_arn, cluster_name,
                                  region, resources):
    """단일 클러스터의 서비스 수집."""
    try:
        svc_paginator = client.get_paginator("list_services")
        svc_pages = svc_paginator.paginate(cluster=cluster_arn)
    except ClientError as e:
        logger.error("ECS list_services failed for %s: %s", cluster_arn, e)
        return

    for svc_page in svc_pages:
        svc_arns = svc_page.get("serviceArns", [])
        if not svc_arns:
            continue

        try:
            desc_resp = client.describe_services(
                cluster=cluster_arn, services=svc_arns)
        except ClientError as e:
            logger.error("ECS describe_services failed for %s: %s",
                         cluster_arn, e)
            continue

        for svc in desc_resp.get("services", []):
            svc_arn = svc.get("serviceArn", "")
            svc_name = svc.get("serviceName", "")
            launch_type = svc.get("launchType", "")

            tags = _get_tags(client, svc_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            tags["_ecs_launch_type"] = launch_type
            tags["_cluster_name"] = cluster_name

            resources.append(
                ResourceInfo(
                    id=svc_name,
                    type="ECS",
                    tags=tags,
                    region=region,
                )
            )


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 ECS 서비스 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/ECS, Compound_Dimension: ClusterName + ServiceName):
    - CPUUtilization (Average) → 'EcsCPU'
    - MemoryUtilization (Average) → 'EcsMemory'
    - RunningTaskCount (Average) → 'RunningTaskCount'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    cluster_name = resource_tags.get("_cluster_name", "")
    dims = [
        {"Name": "ClusterName", "Value": cluster_name},
        {"Name": "ServiceName", "Value": resource_id},
    ]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/ECS", "CPUUtilization", dims,
                    start_time, end_time, "EcsCPU", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ECS", "MemoryUtilization", dims,
                    start_time, end_time, "EcsMemory", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ECS", "RunningTaskCount", dims,
                    start_time, end_time, "RunningTaskCount", metrics, CW_STAT_AVG)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """ECS 서비스 존재 여부 확인."""
    client = _get_ecs_client()
    alive: set[str] = set()

    try:
        cluster_paginator = client.get_paginator("list_clusters")
        cluster_pages = cluster_paginator.paginate()
    except ClientError as e:
        logger.error("ECS list_clusters failed: %s", e)
        return alive

    all_service_names: set[str] = set()
    for cluster_page in cluster_pages:
        for cluster_arn in cluster_page.get("clusterArns", []):
            try:
                svc_paginator = client.get_paginator("list_services")
                svc_pages = svc_paginator.paginate(cluster=cluster_arn)
                for svc_page in svc_pages:
                    for svc_arn in svc_page.get("serviceArns", []):
                        svc_name = svc_arn.rsplit("/", 1)[-1]
                        all_service_names.add(svc_name)
            except ClientError as e:
                logger.error("ECS list_services failed for %s: %s",
                             cluster_arn, e)

    for name in tag_names:
        if name in all_service_names:
            alive.add(name)
        else:
            logger.info("ECS service not found (orphan): %s", name)

    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for ECS %s: no data", result_key,
                    dimensions[1]["Value"] if len(dimensions) > 1 else "unknown")


def _get_tags(ecs_client, resource_arn: str) -> dict:
    """ECS list_tags_for_resource 래퍼. lowercase key/value → 표준 dict 변환."""
    if not resource_arn:
        return {}
    try:
        response = ecs_client.list_tags_for_resource(resourceArn=resource_arn)
        tags = response.get("tags", [])
        return {t["key"]: t["value"] for t in tags}
    except ClientError as e:
        logger.error("ECS list_tags_for_resource failed for %s: %s",
                     resource_arn, e)
        return {}
