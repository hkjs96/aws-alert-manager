"""
RDS·Aurora 수집기 — 엔진·클러스터 판별에 describe가 필요해 나열은 describe, 메트릭은 정의에서 (docs/specs/resource-type-registry P3)

나열: RGT 필터 `rds:db`는 RDS·Aurora·DocDB 인스턴스를 한데 돌려주고 엔진(aurora/docdb)·인스턴스 클래스·Writer/Reader는
describe_db_instances/describe_db_clusters로만 안다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다(태그는 캐시에서).
한 번에 타입 둘(RDS·AuroraRDS)을 내므로 항목이 `(TagName, tags, type)`이다. TagName = DBInstanceIdentifier. 내부 태그
(`_is_serverless_v2`·`_is_cluster_writer`·`_has_readers`·`_total_memory_bytes`·`_total_local_storage_bytes`…)가 알람 정의 변형과 퍼센트 임계치를 가른다.
메트릭: 범용 — daily_monitor가 `get_metrics(id, tags, resource_type=)`로 RDS·AuroraRDS 스펙 중 하나의 정의(변형 반영)를 고른다.
FreeableMemory·FreeStorageSpace·FreeLocalStorage는 정의의 `transform_value`가 bytes→GB로 돌려 태그·기본치(GB)와 바로 비교된다.
2026-09-16까지는 오버라이드 `_metrics`/`get_aurora_metrics`가 개명 전 키(CPU·FreeMemoryGB·FreeStorageGB·Connections…)로 냈고
RDS는 정의 7개 중 4개만, Aurora ReplicaLag는 Average로(정의는 Maximum) 봤다 — 이제 알람 정의와 같은 셋·같은 통계를 본다.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.rds import SPEC
from common.tag_cache import cached_tags

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

# 인스턴스 클래스 → Aurora 로컬(임시) 스토리지 bytes 매핑.
# 출처: AWS "Temporary storage limits for Aurora MySQL" 공식 표(이론적 최대치).
#   https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraMySQL.Managing.Performance.html
# describe_db_instance_classes API가 없는 boto3 버전에서도 동작하도록 정적 매핑을 우선한다.
# 주의:
#  - Aurora PostgreSQL은 값이 다르다(예: t3.medium MySQL=32 vs PostgreSQL≈7.5). 이 맵은
#    MySQL 기준이며, 이 값은 FreeLocalStorage 퍼센트 임계치의 폴백 추정에만 쓰여 비치명적이다.
#  - Serverless v2에는 적용되지 않음(ACU에 비례해 동적 변동 → ACUUtilization으로 감지).
_INSTANCE_CLASS_LOCAL_STORAGE_MAP: dict[str, int] = {
    # T 계열: 전부 32 GiB 고정
    "db.t3.small": 32 * _BYTES_PER_GB,
    "db.t3.medium": 32 * _BYTES_PER_GB,
    "db.t3.large": 32 * _BYTES_PER_GB,
    "db.t4g.medium": 32 * _BYTES_PER_GB,
    "db.t4g.large": 32 * _BYTES_PER_GB,
    # R 계열(r5/r6g/r6i/r7g/r7i): large=32, 이후 xlarge부터 80→2배씩, 16xlarge=1280
    **{
        f"db.{fam}.{size}": gib * _BYTES_PER_GB
        for fam in ("r5", "r6g", "r6i", "r7g", "r7i")
        for size, gib in (
            ("large", 32), ("xlarge", 80), ("2xlarge", 160), ("4xlarge", 320),
            ("8xlarge", 640), ("12xlarge", 960), ("16xlarge", 1280),
        )
    },
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
    except (ClientError, AttributeError) as e:
        # AttributeError: 구버전 boto3는 describe_db_instance_classes 메서드가 없다.
        logger.warning(
            "describe_db_instance_classes failed for %s: %s",
            instance_class, e,
        )
        _instance_class_memory_cache[instance_class] = None
        return None


def _lookup_instance_class_local_storage(instance_class: str) -> int | None:
    """인스턴스 클래스의 로컬 스토리지 용량(bytes) 조회.

    조회 우선순위:
    1. _INSTANCE_CLASS_LOCAL_STORAGE_MAP 정적 매핑 (boto3에 describe_db_instance_classes가
       없는 버전에서도 동작 — Lambda 배포 boto3가 구버전이면 API가 AttributeError로 실패한다)
    2. _instance_class_local_storage_cache 캐시 (API 실패 None 포함)
    3. describe_db_instance_classes API → StorageInfo.StorageSizeRange.Maximum (GiB → bytes)
    """
    # 1순위: 정적 매핑
    static = _INSTANCE_CLASS_LOCAL_STORAGE_MAP.get(instance_class)
    if static is not None:
        return static

    # 2순위: 캐시 (None도 캐시됨 → API 실패 반복 방지)
    if instance_class in _instance_class_local_storage_cache:
        return _instance_class_local_storage_cache[instance_class]

    # 3순위: describe_db_instance_classes API
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


def _enumerate() -> list[tuple[str, dict, str]]:
    """describe_db_instances → 미삭제 → 태그 → Monitoring=on만 엔진으로 가른다(docdb 제외) → 내부 태그. (db_id, tags, RDS|AuroraRDS)."""
    try:
        rds = _get_rds_client()
        paginator = rds.get_paginator("describe_db_instances")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("RDS describe_db_instances failed: %s", e)
        raise

    found: list[tuple[str, dict, str]] = []
    cluster_cache: dict[str, dict | None] = {}

    for page in pages:
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            status = db.get("DBInstanceStatus", "")
            if status in ("deleting", "deleted"):
                logger.info("Skipping RDS instance %s: status=%s", db_id, status)
                continue

            tags = _get_tags(rds, db.get("DBInstanceArn", ""))
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 클러스터·인스턴스 클래스 조회를 아낀다 — 범용 수집기가 같은 필터를 다시 건다

            engine = db.get("Engine", "")
            if engine.lower() == "docdb":
                continue   # DocDB는 docdb 수집기 몫

            resource_type = "AuroraRDS" if "aurora" in engine.lower() else "RDS"
            if resource_type == "AuroraRDS":
                _enrich_aurora_metadata(db, tags, cluster_cache)
            else:
                _enrich_rds_memory(db, tags)
            found.append((db_id, tags, resource_type))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """RDS 인스턴스/Aurora 클러스터 존재 여부 확인.

    tag_names 원소는 식별자이거나 ARN일 수 있다. ARN이 ``:cluster:`` 를 포함하면
    Aurora 클러스터로 보고 describe_db_clusters로, 그 외에는 describe_db_instances로
    조회하되 인스턴스로 못 찾으면 클러스터로 한 번 더 확인한다. **확실히 NotFound인
    것만 orphan(=제외)으로 보고, 스로틀 등 불확실한 오류는 보수적으로 alive로 취급해**
    일시 오류로 라이브 리소스의 알람이 삭제되는 것을 막는다.
    """
    rds = _get_rds_client()
    alive: set[str] = set()
    for tag in tag_names:
        identifier = tag.rsplit(":", 1)[-1] if tag.startswith("arn:") else tag
        if ":cluster:" in tag:
            if _rds_cluster_exists(rds, identifier, tag):
                alive.add(tag)
        elif _rds_instance_exists(rds, identifier, tag) or _rds_cluster_exists(rds, identifier, tag):
            alive.add(tag)
    return alive


def _rds_instance_exists(rds, identifier: str, tag: str) -> bool:
    """인스턴스 존재 시 True, 확실히 NotFound면 False, 불확실하면 보수적으로 True."""
    try:
        rds.describe_db_instances(DBInstanceIdentifier=identifier)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "DBInstanceNotFound":
            return False
        logger.error("RDS instance check uncertain for %s: %s", tag, e)
        return True


def _rds_cluster_exists(rds, identifier: str, tag: str) -> bool:
    """클러스터 존재 시 True, 확실히 NotFound면 False, 불확실하면 보수적으로 True."""
    try:
        rds.describe_db_clusters(DBClusterIdentifier=identifier)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "DBClusterNotFoundFault":
            logger.info("RDS cluster not found (orphan): %s", tag)
            return False
        logger.error("RDS cluster check uncertain for %s: %s", tag, e)
        return True


def _get_tags(rds_client, db_arn: str) -> dict:
    cached = cached_tags(db_arn)
    if cached is not None:
        return cached
    if not db_arn:
        return {}
    try:
        response = rds_client.list_tags_for_resource(ResourceName=db_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("RDS list_tags_for_resource failed for %s: %s", db_arn, e)
        return {}


# RDS 스펙에 묶는다 — 이 수집기는 RDS·AuroraRDS 둘을 내며(_enumerate가 타입을 항목마다 준다) 두 스펙이 collector="rds"로 이걸 가리킨다.
# get_metrics는 resource_type=으로 둘 중 어느 스펙의 정의를 쓸지 고른다(GenericCollector.served_types).
COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
