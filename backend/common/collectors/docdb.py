"""
DocumentDB 수집기 — 엔진 판별에 describe가 필요해 나열은 describe, 메트릭은 GB 변환(오버라이드) (docs/specs/resource-type-registry P3)

나열: RGT 필터 `rds:db`는 RDS·Aurora·DocDB 인스턴스를 한데 돌려주고 엔진은 describe_db_instances로만 안다 — 스펙에 `identity`가 없고
이 모듈의 `_enumerate`(Engine == docdb, deleting/deleted 제외)가 유일한 나열이다(태그는 캐시에서). TagName = DBInstanceIdentifier.
`_enrich_rds_memory`(rds 모듈)가 `_total_memory_bytes` 내부 태그를 붙인다(퍼센트 기반 FreeMemory 임계치).
메트릭(오버라이드 `_metrics`): FreeableMemory/FreeLocalStorage는 bytes → GB 변환 뒤 개명 전 키(`FreeMemoryGB`·`FreeLocalStorageGB`)로
돌려준다 — daily_monitor의 "작을수록 위험" 판정과 GB 단위 임계치가 그 키에 묶여 있다(tasks 3.4). 네임스페이스 AWS/DocDB.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.base import CW_LOOKBACK_MINUTES, CW_STAT_AVG, collect_metric
from common.collectors.generic import GenericCollector
from common.collectors.rds import _enrich_rds_memory
from common.resource_types.docdb import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)

_BYTES_PER_GB = 1024 ** 3


@functools.lru_cache(maxsize=None)
def _get_rds_client():
    """RDS 클라이언트 싱글턴 (DocDB는 동일 API 사용). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("rds")


def _enumerate() -> list[tuple[str, dict]]:
    """describe_db_instances → Engine=docdb·미삭제 → 태그 → Monitoring=on만 메모리 태그를 붙여 (db_id, tags)."""
    try:
        rds = _get_rds_client()
        paginator = rds.get_paginator("describe_db_instances")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("DocDB describe_db_instances failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            if db.get("Engine", "").lower() != "docdb":
                continue
            status = db.get("DBInstanceStatus", "")
            if status in ("deleting", "deleted"):
                logger.info("Skipping DocDB instance %s: status=%s", db_id, status)
                continue
            tags = _get_tags(rds, db.get("DBInstanceArn", ""))
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 인스턴스 클래스 조회를 아낀다 — 범용 수집기가 같은 필터를 다시 건다
            _enrich_rds_memory(db, tags)
            found.append((db_id, tags))
    return found


def _metrics(db_instance_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 DocDB 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/DocDB):
    - CPUUtilization → 'CPU'
    - FreeableMemory (bytes → GB) → 'FreeMemoryGB'
    - FreeLocalStorage (bytes → GB) → 'FreeLocalStorageGB'
    - DatabaseConnections → 'Connections'
    - ReadLatency → 'ReadLatency'
    - WriteLatency → 'WriteLatency'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "DBInstanceIdentifier", "Value": db_instance_id}]
    metrics: dict[str, float] = {}

    collect_metric("AWS/DocDB", "CPUUtilization", dim, start_time, end_time,
                   "CPU", metrics, stat=CW_STAT_AVG, transform=None, resource_label="DocDB")
    collect_metric("AWS/DocDB", "FreeableMemory", dim, start_time, end_time,
                   "FreeMemoryGB", metrics, stat=CW_STAT_AVG,
                   transform=lambda v: v / _BYTES_PER_GB, resource_label="DocDB")
    collect_metric("AWS/DocDB", "FreeLocalStorage", dim, start_time, end_time,
                   "FreeLocalStorageGB", metrics, stat=CW_STAT_AVG,
                   transform=lambda v: v / _BYTES_PER_GB, resource_label="DocDB")
    collect_metric("AWS/DocDB", "DatabaseConnections", dim, start_time, end_time,
                   "Connections", metrics, stat=CW_STAT_AVG, transform=None, resource_label="DocDB")
    collect_metric("AWS/DocDB", "ReadLatency", dim, start_time, end_time,
                   "ReadLatency", metrics, stat=CW_STAT_AVG, transform=None, resource_label="DocDB")
    collect_metric("AWS/DocDB", "WriteLatency", dim, start_time, end_time,
                   "WriteLatency", metrics, stat=CW_STAT_AVG, transform=None, resource_label="DocDB")

    return metrics if metrics else None


def _alive(tag_names: set[str]) -> set[str]:
    """DocDB 인스턴스 존재 여부 확인 (RDS API 사용)."""
    rds = _get_rds_client()
    alive: set[str] = set()
    for db_id in tag_names:
        try:
            rds.describe_db_instances(DBInstanceIdentifier=db_id)
            alive.add(db_id)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "DBInstanceNotFound":
                logger.info("DocDB instance not found (orphan): %s", db_id)
            else:
                logger.error("describe_db_instances failed for %s: %s", db_id, e)
    return alive


def _get_tags(rds_client, db_arn: str) -> dict:
    """RDS list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    cached = cached_tags(db_arn)
    if cached is not None:
        return cached
    if not db_arn:
        return {}
    try:
        response = rds_client.list_tags_for_resource(ResourceName=db_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("DocDB list_tags_for_resource failed for %s: %s", db_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, metrics=_metrics)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
