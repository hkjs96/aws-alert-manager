"""
RDSCollector - Requirements 1.1, 1.2, 1.5, 3.5

Monitoring=on 태그가 있는 RDS 인스턴스 수집 및 CloudWatch 메트릭 조회.
FreeableMemory/FreeStorageSpace는 bytes → GB 변환 후 반환.
"""

import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo

logger = logging.getLogger(__name__)

_CW_PERIOD = 300
_CW_STAT = "Average"
_CW_LOOKBACK_MINUTES = 10
_BYTES_PER_GB = 1024 ** 3


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 RDS 인스턴스 목록 반환.
    삭제 중(deleting) 또는 삭제된 인스턴스는 제외하고 로그 기록.
    """
    try:
        rds = boto3.client("rds")
        paginator = rds.get_paginator("describe_db_instances")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("RDS describe_db_instances failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
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

            region = boto3.session.Session().region_name or "us-east-1"
            resources.append(
                ResourceInfo(
                    id=db_id,
                    type="RDS",
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

    cw = boto3.client("cloudwatch")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=_CW_LOOKBACK_MINUTES)

    dim = [{"Name": "DBInstanceIdentifier", "Value": db_instance_id}]
    metrics: dict[str, float] = {}

    _collect_metric(cw, "AWS/RDS", "CPUUtilization", dim, start_time, end_time,
                    "CPU", metrics, transform=None)
    _collect_metric(cw, "AWS/RDS", "FreeableMemory", dim, start_time, end_time,
                    "FreeMemoryGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric(cw, "AWS/RDS", "FreeStorageSpace", dim, start_time, end_time,
                    "FreeStorageGB", metrics, transform=lambda v: v / _BYTES_PER_GB)
    _collect_metric(cw, "AWS/RDS", "DatabaseConnections", dim, start_time, end_time,
                    "Connections", metrics, transform=None)

    return metrics if metrics else None


def _collect_metric(cw, namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, transform):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip."""
    value = _query_metric(cw, namespace, cw_metric_name, dimensions, start_time, end_time)
    if value is not None:
        metrics_dict[result_key] = transform(value) if transform else value
    else:
        logger.info("Skipping %s metric for RDS %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _query_metric(cw, namespace, metric_name, dimensions, start_time, end_time) -> float | None:
    try:
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=_CW_PERIOD,
            Statistics=[_CW_STAT],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        latest = max(datapoints, key=lambda d: d["Timestamp"])
        return latest[_CW_STAT]
    except ClientError as e:
        logger.error("CloudWatch query failed for %s/%s: %s", namespace, metric_name, e)
        return None


def _get_tags(rds_client, db_arn: str) -> dict:
    if not db_arn:
        return {}
    try:
        response = rds_client.list_tags_for_resource(ResourceName=db_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("RDS list_tags_for_resource failed for %s: %s", db_arn, e)
        return {}
