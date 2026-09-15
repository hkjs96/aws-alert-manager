"""
ElastiCache 수집기 — 엔진·상태 필터가 describe를 요구하므로 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

Redis/Valkey 클러스터만 대상이고 deleting/deleted는 제외한다. RGT는 엔진도 상태도 모르며 memcached까지 돌려주므로 describe가
어차피 필요하다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다(태그는 캐시에서 읽는다). TagName = CacheClusterId.
메트릭은 스펙(`common/resource_types/elasticache.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/ElastiCache, 디멘션 CacheClusterId.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.elasticache import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_elasticache_client():
    """ElastiCache 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elasticache")


def _enumerate() -> list[tuple[str, dict]]:
    """describe_cache_clusters(ShowCacheNodeInfo) → Redis/Valkey·미삭제 클러스터 (cluster_id, tags)."""
    try:
        client = _get_elasticache_client()
        paginator = client.get_paginator("describe_cache_clusters")
        pages = paginator.paginate(ShowCacheNodeInfo=True)
    except ClientError as e:
        logger.error("ElastiCache describe_cache_clusters failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for cluster in page.get("CacheClusters", []):
            cluster_id = cluster["CacheClusterId"]
            engine = cluster.get("Engine", "")
            if engine.lower() not in ("redis", "valkey"):
                continue
            status = cluster.get("CacheClusterStatus", "")
            if status in ("deleting", "deleted"):
                logger.info("Skipping ElastiCache cluster %s: status=%s", cluster_id, status)
                continue
            found.append((cluster_id, _get_tags(client, cluster.get("ARN", ""))))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """ElastiCache 클러스터 존재 여부 확인 — describe_cache_clusters(CacheClusterId)."""
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
    cached = cached_tags(cluster_arn)
    if cached is not None:
        return cached
    if not cluster_arn:
        return {}
    try:
        response = elasticache_client.list_tags_for_resource(ResourceName=cluster_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("ElastiCache list_tags_for_resource failed for %s: %s", cluster_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
