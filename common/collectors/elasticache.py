"""
ElastiCacheCollector - Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7

Monitoring=on 태그가 있는 ElastiCache Redis 노드 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/ElastiCache, 디멘션: CacheClusterId.
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
def _get_elasticache_client():
    """ElastiCache 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elasticache")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 ElastiCache Redis 노드 목록 반환.

    Engine == "redis" 인 클러스터만 수집.
    삭제 중(deleting) 또는 삭제된(deleted) 클러스터는 제외하고 로그 기록.
    """
    try:
        client = _get_elasticache_client()
        paginator = client.get_paginator("describe_cache_clusters")
        pages = paginator.paginate(ShowCacheNodeInfo=True)
    except ClientError as e:
        logger.error("ElastiCache describe_cache_clusters failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    for page in pages:
        for cluster in page.get("CacheClusters", []):
            cluster_id = cluster["CacheClusterId"]
            engine = cluster.get("Engine", "")

            if engine.lower() != "redis":
                continue

            status = cluster.get("CacheClusterStatus", "")
            if status in ("deleting", "deleted"):
                logger.info("Skipping ElastiCache cluster %s: status=%s", cluster_id, status)
                continue

            arn = cluster.get("ARN", "")
            tags = _get_tags(client, arn)

            if tags.get("Monitoring", "").lower() != "on":
                continue

            region = boto3.session.Session().region_name or "us-east-1"
            resources.append(
                ResourceInfo(
                    id=cluster_id,
                    type="ElastiCache",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 ElastiCache 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/ElastiCache):
    - CPUUtilization → 'CPU'
    - EngineCPUUtilization → 'EngineCPU'
    - SwapUsage → 'SwapUsage'
    - Evictions → 'Evictions'
    - CurrConnections → 'CurrConnections'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "CacheClusterId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/ElastiCache", "CPUUtilization", dim, start_time, end_time,
                    "CPU", metrics)
    _collect_metric("AWS/ElastiCache", "EngineCPUUtilization", dim, start_time, end_time,
                    "EngineCPU", metrics)
    _collect_metric("AWS/ElastiCache", "SwapUsage", dim, start_time, end_time,
                    "SwapUsage", metrics)
    _collect_metric("AWS/ElastiCache", "Evictions", dim, start_time, end_time,
                    "Evictions", metrics)
    _collect_metric("AWS/ElastiCache", "CurrConnections", dim, start_time, end_time,
                    "CurrConnections", metrics)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_AVG)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for ElastiCache %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """ElastiCache 클러스터 존재 여부 확인."""
    client = _get_elasticache_client()
    alive: set[str] = set()
    for cid in tag_names:
        try:
            client.describe_cache_clusters(CacheClusterId=cid)
            alive.add(cid)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "CacheClusterNotFound":
                logger.info("ElastiCache cluster not found (orphan): %s", cid)
            else:
                logger.error("describe_cache_clusters failed for %s: %s", cid, e)
    return alive


def _get_tags(elasticache_client, cluster_arn: str) -> dict:
    """ElastiCache list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not cluster_arn:
        return {}
    try:
        response = elasticache_client.list_tags_for_resource(ResourceName=cluster_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("ElastiCache list_tags_for_resource failed for %s: %s", cluster_arn, e)
        return {}
