"""
DocDBCollector - Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1~2.9

Monitoring=on 태그가 있는 DocumentDB 인스턴스 수집 및 CloudWatch 메트릭 조회.
FreeableMemory/FreeLocalStorage는 bytes → GB 변환 후 반환.
네임스페이스: AWS/DocDB, 디멘션: DBInstanceIdentifier.
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
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_rds_client():
    """RDS 클라이언트 싱글턴 (DocDB는 동일 API 사용). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("rds")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 DocumentDB 인스턴스 목록 반환.

    Engine == "docdb" 인스턴스만 수집.
    삭제 중(deleting) 또는 삭제된(deleted) 인스턴스는 제외하고 로그 기록.
    """
    try:
        rds = _get_rds_client()
        paginator = rds.get_paginator("describe_db_instances")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("DocDB describe_db_instances failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    for page in pages:
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            engine = db.get("Engine", "")

            # DocDB 엔진만 수집 (정확 매칭)
            if engine.lower() != "docdb":
                continue

            status = db.get("DBInstanceStatus", "")
            if status in ("deleting", "deleted"):
                logger.info("Skipping DocDB instance %s: status=%s", db_id, status)
                continue

            db_arn = db.get("DBInstanceArn", "")
            tags = _get_tags(rds, db_arn)

            if tags.get("Monitoring", "").lower() != "on":
                continue

            region = boto3.session.Session().region_name or "us-east-1"
            resources.append(
                ResourceInfo(
                    id=db_id,
                    type="DocDB",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    db_instance_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
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

    _collect_metric("AWS/DocDB", "CPUUtilization", dim, start_time, end_time,
                    "CPU", metrics, transform=None)
    _collect_metric("AWS/DocDB", "FreeableMemory", dim, start_time, end_time,
                    "FreeMemoryGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric("AWS/DocDB", "FreeLocalStorage", dim, start_time, end_time,
                    "FreeLocalStorageGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric("AWS/DocDB", "DatabaseConnections", dim, start_time, end_time,
                    "Connections", metrics, transform=None)
    _collect_metric("AWS/DocDB", "ReadLatency", dim, start_time, end_time,
                    "ReadLatency", metrics, transform=None)
    _collect_metric("AWS/DocDB", "WriteLatency", dim, start_time, end_time,
                    "WriteLatency", metrics, transform=None)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, transform):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_AVG)
    if value is not None:
        metrics_dict[result_key] = transform(value) if transform else value
    else:
        logger.info("Skipping %s metric for DocDB %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
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
                logger.error(
                    "describe_db_instances failed for %s: %s", db_id, e,
                )

    return alive


def _get_tags(rds_client, db_arn: str) -> dict:
    """RDS list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not db_arn:
        return {}
    try:
        response = rds_client.list_tags_for_resource(ResourceName=db_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("DocDB list_tags_for_resource failed for %s: %s", db_arn, e)
        return {}
