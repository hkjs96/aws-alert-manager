"""
MSKCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 MSK 클러스터 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/Kafka, 디멘션: "Cluster Name" (공백 포함).
list_clusters_v2()는 Tags를 dict로 직접 반환.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, collect_metric

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_kafka_client():
    """Kafka 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("kafka")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 MSK 클러스터 목록 반환.

    list_clusters_v2() paginator로 전체 클러스터 조회.
    Tags 필드가 dict로 직접 포함되어 있으므로 별도 태그 API 호출 불필요.
    """
    try:
        client = _get_kafka_client()
        paginator = client.get_paginator("list_clusters_v2")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("MSK list_clusters_v2 failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for cluster in page.get("ClusterInfoList", []):
            tags = cluster.get("Tags", {})
            if tags.get("Monitoring", "").lower() != "on":
                continue

            cluster_name = cluster["ClusterName"]
            resources.append(
                ResourceInfo(
                    id=cluster_name,
                    type="MSK",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 MSK 클러스터 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/Kafka):
    - SumOffsetLag (Maximum) → 'OffsetLag'
    - BytesInPerSec (Average) → 'BytesInPerSec'
    - UnderReplicatedPartitions (Maximum) → 'UnderReplicatedPartitions'
    - ActiveControllerCount (Average) → 'ActiveControllerCount'

    디멘션 키: "Cluster Name" (공백 포함, AWS 공식 문서 기준).
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "Cluster Name", "Value": resource_id}]
    metrics: dict[str, float] = {}

    collect_metric("AWS/Kafka", "SumOffsetLag", dim,
                   start_time, end_time, "OffsetLag", metrics,
                   stat="Maximum", resource_label="MSK")
    collect_metric("AWS/Kafka", "BytesInPerSec", dim,
                   start_time, end_time, "BytesInPerSec", metrics,
                   stat=CW_STAT_AVG, resource_label="MSK")
    collect_metric("AWS/Kafka", "UnderReplicatedPartitions", dim,
                   start_time, end_time, "UnderReplicatedPartitions", metrics,
                   stat="Maximum", resource_label="MSK")
    collect_metric("AWS/Kafka", "ActiveControllerCount", dim,
                   start_time, end_time, "ActiveControllerCount", metrics,
                   stat=CW_STAT_AVG, resource_label="MSK")

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """MSK 클러스터 존재 여부 확인."""
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

