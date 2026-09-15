"""
EFS 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

TagName = 파일시스템 ID(ARN `file-system/<fs-id>`의 마지막 조각, 스펙 `identity`). 메트릭은 스펙(`common/resource_types/efs.py`)의
알람 정의에서 만든다. 네임스페이스 AWS/EFS, 디멘션 FileSystemId. describe_file_systems 응답이 Tags를 포함한다.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.efs import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_efs_client():
    """EFS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("efs")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: describe_file_systems(Tags 포함, 태그 API 없음). (fs_id, tags)."""
    try:
        client = _get_efs_client()
        paginator = client.get_paginator("describe_file_systems")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("EFS describe_file_systems failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for fs in page.get("FileSystems", []):
            found.append((fs["FileSystemId"], {t["Key"]: t["Value"] for t in fs.get("Tags", [])}))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """EFS 파일시스템 존재 여부 확인 — describe_file_systems(FileSystemId)."""
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


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
