"""
Direct Connect 수집기 — connectionState='available' 필터가 describe를 요구하므로 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

RGT는 연결 상태를 모른다. 상태 필터에 describe_connections(1콜)가 어차피 필요하고 태그는 캐시(`cached_tags`)에서 읽으므로 RGT
나열로 아낄 콜이 없다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다. TagName = connectionId.
메트릭은 스펙(`common/resource_types/dx.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/DX, 디멘션 ConnectionId.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.dx import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_dx_client():
    """DirectConnect 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("directconnect")


def _enumerate() -> list[tuple[str, dict]]:
    """connectionState='available' Direct Connect 연결 (connection_id, tags).

    describe_connections()로 전체 연결 조회 후 connectionState 필터링, describe_tags()로 태그 확인.
    DX describe_tags는 lowercase key 사용: {"key": ..., "value": ...}.
    """
    try:
        client = _get_dx_client()
        response = client.describe_connections()
    except ClientError as e:
        logger.error("DX describe_connections failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for conn in response.get("connections", []):
        conn_id = conn["connectionId"]
        if conn.get("connectionState", "") != "available":
            continue

        # DX ARN 구성
        owner = conn.get("ownerAccount", "")
        conn_region = conn.get("region", region)
        conn_arn = f"arn:aws:directconnect:{conn_region}:{owner}:dxcon/{conn_id}"
        found.append((conn_id, _get_tags(client, conn_arn)))

    return found


def _alive(tag_names: set[str]) -> set[str]:
    """Direct Connect 연결 존재 여부 확인 — describe_connections 전체와 교집합."""
    client = _get_dx_client()
    alive: set[str] = set()
    try:
        response = client.describe_connections()
        existing_ids = {c["connectionId"] for c in response.get("connections", [])}
    except ClientError as e:
        logger.error("DX describe_connections failed: %s", e)
        return alive

    for conn_id in tag_names:
        if conn_id in existing_ids:
            alive.add(conn_id)
        else:
            logger.info("DX connection not found (orphan): %s", conn_id)
    return alive


def _get_tags(dx_client, connection_arn: str) -> dict:
    """DX describe_tags 래퍼. DX는 lowercase key 사용: {key: ..., value: ...}."""
    cached = cached_tags(connection_arn)
    if cached is not None:
        return cached
    try:
        response = dx_client.describe_tags(resourceArns=[connection_arn])
        tags = {}
        for rt in response.get("resourceTags", []):
            for tag in rt.get("tags", []):
                tags[tag.get("key", "")] = tag.get("value", "")
        return tags
    except ClientError as e:
        logger.error("DX describe_tags failed for %s: %s", connection_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
