"""
EFSCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 EFS 파일시스템 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/EFS, 디멘션: FileSystemId.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_efs_client():
    """EFS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("efs")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 EFS 파일시스템 목록 반환.

    describe_file_systems() paginator로 전체 파일시스템 조회.
    응답의 Tags 필드에서 Monitoring=on 필터링.
    """
    try:
        client = _get_efs_client()
        paginator = client.get_paginator("describe_file_systems")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("EFS describe_file_systems failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for fs in page.get("FileSystems", []):
            fs_id = fs["FileSystemId"]
            tags = {t["Key"]: t["Value"] for t in fs.get("Tags", [])}

            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=fs_id,
                    type="EFS",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 EFS 파일시스템 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/EFS):
    - BurstCreditBalance (Minimum) → 'BurstCreditBalance'
    - PercentIOLimit (Average) → 'PercentIOLimit'
    - ClientConnections (Sum) → 'EFSClientConnections'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "FileSystemId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/EFS", "BurstCreditBalance", dim,
                    start_time, end_time, "BurstCreditBalance", metrics, "Minimum")
    _collect_metric("AWS/EFS", "PercentIOLimit", dim,
                    start_time, end_time, "PercentIOLimit", metrics, CW_STAT_AVG)
    _collect_metric("AWS/EFS", "ClientConnections", dim,
                    start_time, end_time, "EFSClientConnections", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """EFS 파일시스템 존재 여부 확인."""
    client = _get_efs_client()
    alive: set[str] = set()
    for fs_id in tag_names:
        try:
            client.describe_file_systems(FileSystemId=fs_id)
            alive.add(fs_id)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "FileSystemNotFound":
                logger.info("EFS file system not found (orphan): %s", fs_id)
            else:
                logger.error("describe_file_systems failed for %s: %s", fs_id, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for EFS %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")
