"""
RDSCollector - Requirements 1.1, 1.2, 1.5, 3.5

Monitoring=on 태그가 있는 RDS 인스턴스 수집 및 CloudWatch 메트릭 조회.
FreeableMemory/FreeStorageSpace는 bytes → GB 변환 후 반환.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG

logger = logging.getLogger(__name__)

_BYTES_PER_GB = 1024 ** 3

# ──────────────────────────────────────────────
# 인스턴스 클래스 → 메모리 bytes 매핑 (design §1)
# ──────────────────────────────────────────────

_INSTANCE_CLASS_MEMORY_MAP: dict[str, int] = {
    # T3/T4g (burstable)
    "db.t3.micro": 1 * _BYTES_PER_GB,
    "db.t3.small": 2 * _BYTES_PER_GB,
    "db.t3.medium": 4 * _BYTES_PER_GB,
    "db.t3.large": 8 * _BYTES_PER_GB,
    "db.t4g.micro": 1 * _BYTES_PER_GB,
    "db.t4g.small": 2 * _BYTES_PER_GB,
    "db.t4g.medium": 4 * _BYTES_PER_GB,
    "db.t4g.large": 8 * _BYTES_PER_GB,
    # M5/M6g/M7g (general purpose, RDS)
    "db.m5.large": 8 * _BYTES_PER_GB,
    "db.m5.xlarge": 16 * _BYTES_PER_GB,
    "db.m5.2xlarge": 32 * _BYTES_PER_GB,
    "db.m5.4xlarge": 64 * _BYTES_PER_GB,
    "db.m6g.large": 8 * _BYTES_PER_GB,
    "db.m6g.xlarge": 16 * _BYTES_PER_GB,
    "db.m6g.2xlarge": 32 * _BYTES_PER_GB,
    "db.m6g.4xlarge": 64 * _BYTES_PER_GB,
    "db.m7g.large": 8 * _BYTES_PER_GB,
    "db.m7g.xlarge": 16 * _BYTES_PER_GB,
    "db.m7g.2xlarge": 32 * _BYTES_PER_GB,
    "db.m7g.4xlarge": 64 * _BYTES_PER_GB,
    # R6g/R7g (memory optimized, Aurora/RDS)
    "db.r6g.large": 16 * _BYTES_PER_GB,
    "db.r6g.xlarge": 32 * _BYTES_PER_GB,
    "db.r6g.2xlarge": 64 * _BYTES_PER_GB,
    "db.r6g.4xlarge": 128 * _BYTES_PER_GB,
    "db.r6g.8xlarge": 256 * _BYTES_PER_GB,
    "db.r6g.12xlarge": 384 * _BYTES_PER_GB,
    "db.r6g.16xlarge": 512 * _BYTES_PER_GB,
    "db.r7g.large": 16 * _BYTES_PER_GB,
    "db.r7g.xlarge": 32 * _BYTES_PER_GB,
    "db.r7g.2xlarge": 64 * _BYTES_PER_GB,
    "db.r7g.4xlarge": 128 * _BYTES_PER_GB,
    "db.r7g.8xlarge": 256 * _BYTES_PER_GB,
    "db.r7g.12xlarge": 384 * _BYTES_PER_GB,
    "db.r7g.16xlarge": 512 * _BYTES_PER_GB,
}


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

_instance_class_memory_cache: dict[str, int | None] = {}
_instance_class_local_storage_cache: dict[str, int | None] = {}


@functools.lru_cache(maxsize=None)
def _get_rds_client():
    """RDS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("rds")


def _lookup_instance_class_memory(instance_class: str) -> int | None:
    """인스턴스 클래스의 메모리 용량(bytes) 조회.

    조회 우선순위:
    1. _INSTANCE_CLASS_MEMORY_MAP 정적 매핑
    2. _instance_class_memory_cache 캐시 (API 실패 None 포함)
    3. describe_db_instance_classes API 동적 조회
    """
    # 1순위: 정적 매핑
    static = _INSTANCE_CLASS_MEMORY_MAP.get(instance_class)
    if static is not None:
        return static

    # 2순위: 캐시 (None도 캐시됨 → API 실패 반복 방지)
    if instance_class in _instance_class_memory_cache:
        return _instance_class_memory_cache[instance_class]

    # 3순위: describe_db_instance_classes API
    try:
        rds = _get_rds_client()
        resp = rds.describe_db_instance_classes(
            DBInstanceClass=instance_class,
        )
        db_classes = resp.get("DBInstanceClasses", [])
        if db_classes:
            memory_mib = db_classes[0].get("Memory", 0)
            memory_bytes = memory_mib * 1024 * 1024
            _instance_class_memory_cache[instance_class] = memory_bytes
            return memory_bytes
        _instance_class_memory_cache[instance_class] = None
        return None
    except ClientError as e:
        logger.warning(
            "describe_db_instance_classes failed for %s: %s",
            instance_class, e,
        )
        _instance_class_memory_cache[instance_class] = None
        return None


def _lookup_instance_class_local_storage(instance_class: str) -> int | None:
    """인스턴스 클래스의 로컬 스토리지 용량(bytes) 조회.

    조회 우선순위:
    1. _instance_class_local_storage_cache 캐시 (API 실패 None 포함)
    2. describe_db_instance_classes API → StorageInfo.StorageSizeRange.Maximum (GiB → bytes)
    """
    # 1순위: 캐시 (None도 캐시됨 → API 실패 반복 방지)
    if instance_class in _instance_class_local_storage_cache:
        return _instance_class_local_storage_cache[instance_class]

    # 2순위: describe_db_instance_classes API
    try:
        rds = _get_rds_client()
        resp = rds.describe_db_instance_classes(
            DBInstanceClass=instance_class,
        )
        db_classes = resp.get("DBInstanceClasses", [])
        if db_classes:
            storage_info = db_classes[0].get("StorageInfo", {})
            if isinstance(storage_info, dict):
                size_range = storage_info.get("StorageSizeRange", {})
                if isinstance(size_range, dict):
                    max_gib = size_range.get("Maximum", 0)
                    if isinstance(max_gib, (int, float)) and max_gib > 0:
                        storage_bytes = int(max_gib) * _BYTES_PER_GB
                        _instance_class_local_storage_cache[instance_class] = storage_bytes
                        return storage_bytes
        _instance_class_local_storage_cache[instance_class] = None
        return None
    except (ClientError, AttributeError) as e:
        logger.warning(
            "describe_db_instance_classes failed for %s (local storage): %s",
            instance_class, e,
        )
        _instance_class_local_storage_cache[instance_class] = None
        return None


def _get_cluster_info(cluster_id: str) -> dict | None:
    """describe_db_clusters 래퍼. ClientError 시 None 반환 + error 로그."""
    try:
        rds = _get_rds_client()
        resp = rds.describe_db_clusters(
            DBClusterIdentifier=cluster_id,
        )
        clusters = resp.get("DBClusters", [])
        return clusters[0] if clusters else None
    except ClientError as e:
        logger.error(
            "describe_db_clusters failed for %s: %s", cluster_id, e,
        )
        return None


def _enrich_aurora_metadata(
    db_instance: dict, tags: dict, cluster_cache: dict,
) -> None:
    """Aurora 인스턴스 태그에 내부 메타데이터 추가."""
    instance_class = db_instance.get("DBInstanceClass", "")
    tags["_db_instance_class"] = instance_class

    is_serverless = instance_class == "db.serverless"
    tags["_is_serverless_v2"] = "true" if is_serverless else "false"

    # 클러스터 정보 조회 (캐싱)
    cluster_id = db_instance.get("DBClusterIdentifier", "")
    if not cluster_id:
        return

    if cluster_id not in cluster_cache:
        cluster_cache[cluster_id] = _get_cluster_info(cluster_id)

    cluster = cluster_cache[cluster_id]
    if cluster is None:
        return

    # writer/reader 판별
    db_id = db_instance["DBInstanceIdentifier"]
    members = cluster.get("DBClusterMembers", [])
    for member in members:
        if member["DBInstanceIdentifier"] == db_id:
            is_writer = member.get("IsClusterWriter", False)
            tags["_is_cluster_writer"] = "true" if is_writer else "false"
            break

    tags["_has_readers"] = "true" if len(members) > 1 else "false"

    # Serverless v2 ACU 정보
    if is_serverless:
        sv2_config = cluster.get("ServerlessV2ScalingConfiguration")
        if sv2_config:
            max_acu = sv2_config.get("MaxCapacity", 0)
            min_acu = sv2_config.get("MinCapacity", 0)
            tags["_max_acu"] = str(max_acu)
            tags["_min_acu"] = str(min_acu)
            tags["_total_memory_bytes"] = str(
                int(max_acu * 2 * 1073741824)
            )
        else:
            logger.warning(
                "ServerlessV2ScalingConfiguration missing for %s",
                cluster_id,
            )
    else:
        # Provisioned: 인스턴스 클래스 메모리 lookup (정적 매핑 → API 동적 조회)
        memory = _lookup_instance_class_memory(instance_class)
        if memory is not None:
            tags["_total_memory_bytes"] = str(memory)
        else:
            logger.warning(
                "Unknown instance class %s for %s, "
                "skipping _total_memory_bytes",
                instance_class,
                db_id,
            )

        # Provisioned: 로컬 스토리지 용량 lookup (API 동적 조회)
        local_storage = _lookup_instance_class_local_storage(instance_class)
        if local_storage is not None:
            tags["_total_local_storage_bytes"] = str(local_storage)
        else:
            logger.warning(
                "Unknown local storage for %s (%s), "
                "skipping _total_local_storage_bytes",
                instance_class,
                db_id,
            )


def _enrich_rds_memory(db_instance: dict, tags: dict) -> None:
    """일반 RDS 인스턴스에 메모리 용량 태그 추가 (퍼센트 기반 FreeMemory 임계치용)."""
    instance_class = db_instance.get("DBInstanceClass", "")
    if not instance_class:
        return
    tags["_db_instance_class"] = instance_class
    memory = _lookup_instance_class_memory(instance_class)
    if memory is not None:
        tags["_total_memory_bytes"] = str(memory)
    else:
        logger.warning(
            "Unknown instance class %s for %s, skipping _total_memory_bytes",
            instance_class,
            db_instance.get("DBInstanceIdentifier", "unknown"),
        )


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 RDS 인스턴스 목록 반환.
    삭제 중(deleting) 또는 삭제된 인스턴스는 제외하고 로그 기록.
    """
    try:
        rds = _get_rds_client()
        paginator = rds.get_paginator("describe_db_instances")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("RDS describe_db_instances failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    cluster_cache: dict[str, dict | None] = {}
    for page in pages:
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            status = db.get("DBInstanceStatus", "")

            if status in ("deleting", "deleted"):
                logger.info("Skipping RDS instance %s: status=%s", db_id, status)
                continue

            # RDS 태그는 별도 API 호출 필요
            db_arn = db.get("DBInstanceArn", "")
            tags = _get_tags(rds, db_arn)

            if tags.get("Monitoring", "").lower() != "on":
                continue

            engine = db.get("Engine", "")

            # DocDB 엔진은 별도 Collector(docdb.py)에서 처리하므로 제외
            if engine.lower() == "docdb":
                continue

            resource_type = "AuroraRDS" if "aurora" in engine.lower() else "RDS"

            if resource_type == "AuroraRDS":
                _enrich_aurora_metadata(db, tags, cluster_cache)
            else:
                # 일반 RDS: 인스턴스 클래스 메모리 lookup (퍼센트 기반 FreeMemory 임계치용)
                _enrich_rds_memory(db, tags)

            region = boto3.session.Session().region_name or "us-east-1"
            resources.append(
                ResourceInfo(
                    id=db_id,
                    type=resource_type,
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(db_instance_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 RDS 메트릭 조회.

    수집 메트릭:
    - CPUUtilization → 'CPU'
    - FreeableMemory (bytes → GB) → 'FreeMemoryGB'
    - FreeStorageSpace (bytes → GB) → 'FreeStorageGB'
    - DatabaseConnections → 'Connections'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "DBInstanceIdentifier", "Value": db_instance_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/RDS", "CPUUtilization", dim, start_time, end_time,
                    "CPU", metrics, transform=None)
    _collect_metric("AWS/RDS", "FreeableMemory", dim, start_time, end_time,
                    "FreeMemoryGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric("AWS/RDS", "FreeStorageSpace", dim, start_time, end_time,
                    "FreeStorageGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric("AWS/RDS", "DatabaseConnections", dim, start_time, end_time,
                    "Connections", metrics, transform=None)

    return metrics if metrics else None


def get_aurora_metrics(db_instance_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 Aurora RDS 메트릭 조회 (변형별 조건부 분기).

    Always 수집:
    - CPUUtilization → 'CPU'
    - FreeableMemory (bytes → GB) → 'FreeMemoryGB'
    - DatabaseConnections → 'Connections'

    조건부 수집:
    - _is_serverless_v2 != "true": FreeLocalStorage → 'FreeLocalStorageGB'
    - _is_serverless_v2 == "true": ACUUtilization, ServerlessDatabaseCapacity
    - _is_cluster_writer == "true" & _has_readers == "true":
      AuroraReplicaLagMaximum → 'ReplicaLag'
    - _is_cluster_writer == "false": AuroraReplicaLag → 'ReaderReplicaLag'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "DBInstanceIdentifier", "Value": db_instance_id}]
    metrics: dict[str, float] = {}

    # Always: CPU, Connections
    _collect_metric("AWS/RDS", "CPUUtilization", dim, start_time, end_time,
                    "CPU", metrics, transform=None)
    _collect_metric("AWS/RDS", "DatabaseConnections", dim, start_time, end_time,
                    "Connections", metrics, transform=None)

    is_serverless = resource_tags.get("_is_serverless_v2") == "true"
    is_writer = resource_tags.get("_is_cluster_writer") == "true"
    has_readers = resource_tags.get("_has_readers") == "true"

    # Provisioned: FreeMemoryGB, FreeLocalStorageGB
    if not is_serverless:
        _collect_metric("AWS/RDS", "FreeableMemory", dim, start_time, end_time,
                        "FreeMemoryGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
        _collect_metric("AWS/RDS", "FreeLocalStorage", dim, start_time, end_time,
                        "FreeLocalStorageGB", metrics, transform=lambda v: v / _BYTES_PER_GB)

    # Serverless v2: ACUUtilization only (FreeableMemory/ServerlessDatabaseCapacity 제외)
    if is_serverless:
        _collect_metric("AWS/RDS", "ACUUtilization", dim, start_time, end_time,
                        "ACUUtilization", metrics, transform=None)

    # Writer with readers: AuroraReplicaLagMaximum → ReplicaLag
    if is_writer and has_readers:
        _collect_metric("AWS/RDS", "AuroraReplicaLagMaximum", dim, start_time, end_time,
                        "ReplicaLag", metrics, transform=None)

    # Reader: AuroraReplicaLag → ReaderReplicaLag
    if not is_writer:
        _collect_metric("AWS/RDS", "AuroraReplicaLag", dim, start_time, end_time,
                        "ReaderReplicaLag", metrics, transform=None)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, transform):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_AVG)
    if value is not None:
        metrics_dict[result_key] = transform(value) if transform else value
    else:
        logger.info("Skipping %s metric for RDS %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(rds_client, db_arn: str) -> dict:
    if not db_arn:
        return {}
    try:
        response = rds_client.list_tags_for_resource(ResourceName=db_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("RDS list_tags_for_resource failed for %s: %s", db_arn, e)
        return {}
