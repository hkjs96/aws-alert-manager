"""
AWS Backup 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 볼트 이름(ARN `backup-vault:<name>`의 마지막 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/backup.py`)의
알람 정의에서 만든다. 네임스페이스 AWS/Backup, 디멘션 BackupVaultName.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.backup import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_backup_client():
    """Backup 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("backup")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_backup_vaults 후 볼트마다 list_tags(N+1). (vault_name, tags)."""
    try:
        client = _get_backup_client()
        paginator = client.get_paginator("list_backup_vaults")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Backup list_backup_vaults failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for vault in page.get("BackupVaultList", []):
            found.append((vault["BackupVaultName"], _get_tags(client, vault.get("BackupVaultArn", ""))))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """Backup Vault 존재 여부 확인 — describe_backup_vault."""
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


def _get_tags(backup_client, vault_arn: str) -> dict:
    """Backup list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    cached = cached_tags(vault_arn)
    if cached is not None:
        return cached
    if not vault_arn:
        return {}
    try:
        response = backup_client.list_tags(ResourceArn=vault_arn)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("Backup list_tags failed for %s: %s", vault_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
