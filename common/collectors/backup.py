"""
BackupCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 AWS Backup Vault 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/Backup, 디멘션: BackupVaultName.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_backup_client():
    """Backup 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("backup")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 Backup Vault 목록 반환.

    list_backup_vaults() paginator로 전체 vault 조회 후
    list_tags()로 태그 확인, Monitoring=on 필터링.
    """
    try:
        client = _get_backup_client()
        paginator = client.get_paginator("list_backup_vaults")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Backup list_backup_vaults failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for vault in page.get("BackupVaultList", []):
            vault_name = vault["BackupVaultName"]
            vault_arn = vault.get("BackupVaultArn", "")

            tags = _get_tags(client, vault_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=vault_name,
                    type="Backup",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 Backup Vault 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/Backup, stat: Sum):
    - NumberOfBackupJobsFailed → 'BackupJobsFailed'
    - NumberOfBackupJobsAborted → 'BackupJobsAborted'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "BackupVaultName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/Backup", "NumberOfBackupJobsFailed", dim,
                    start_time, end_time, "BackupJobsFailed", metrics)
    _collect_metric("AWS/Backup", "NumberOfBackupJobsAborted", dim,
                    start_time, end_time, "BackupJobsAborted", metrics)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """Backup Vault 존재 여부 확인."""
    client = _get_backup_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.describe_backup_vault(BackupVaultName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("Backup vault not found (orphan): %s", name)
            else:
                logger.error("describe_backup_vault failed for %s: %s", name, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_SUM)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for Backup %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(backup_client, vault_arn: str) -> dict:
    """Backup list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not vault_arn:
        return {}
    try:
        response = backup_client.list_tags(ResourceArn=vault_arn)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("Backup list_tags failed for %s: %s", vault_arn, e)
        return {}
