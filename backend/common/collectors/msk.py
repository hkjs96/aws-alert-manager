"""
MSK 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 클러스터 이름(ARN `cluster/<name>/<uuid>`의 가운데 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/msk.py`)의
알람 정의에서 만든다. 네임스페이스 AWS/Kafka, 디멘션 "Cluster Name"(공백 포함). list_clusters_v2는 Tags를 dict로 직접 준다.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.msk import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_kafka_client():
    """Kafka 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("kafka")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_clusters_v2(Tags 포함, 태그 API 없음). (cluster_name, tags)."""
    try:
        client = _get_kafka_client()
        paginator = client.get_paginator("list_clusters_v2")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("MSK list_clusters_v2 failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for cluster in page.get("ClusterInfoList", []):
            found.append((cluster["ClusterName"], cluster.get("Tags", {})))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """MSK 클러스터 존재 여부 확인 — list_clusters_v2 전체와 교집합."""
    client = _get_kafka_client()
    alive: set[str] = set()
    try:
        paginator = client.get_paginator("list_clusters_v2")
        existing_names: set[str] = set()
        for page in paginator.paginate():
            for cluster in page.get("ClusterInfoList", []):
                existing_names.add(cluster["ClusterName"])
    except ClientError as e:
        logger.error("MSK list_clusters_v2 failed: %s", e)
        return alive

    for name in tag_names:
        if name in existing_names:
            alive.add(name)
        else:
            logger.info("MSK cluster not found (orphan): %s", name)
    return alive


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
