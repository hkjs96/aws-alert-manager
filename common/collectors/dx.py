"""
DXCollector - Extended Resource Monitoring

Monitoring=on 태그가 있는 Direct Connect 연결 수집 및 CloudWatch 메트릭 조회.
connectionState=='available' 연결만 대상.
네임스페이스: AWS/DX, 디멘션: ConnectionId.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_dx_client():
    """DirectConnect 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("directconnect")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그 + connectionState='available' Direct Connect 연결 목록 반환.

    describe_connections()로 전체 연결 조회 후
    connectionState 필터링, describe_tags()로 태그 확인.
    DX describe_tags는 lowercase key 사용: {"key": ..., "value": ...}.
    """
    try:
        client = _get_dx_client()
        response = client.describe_connections()
    except ClientError as e:
        logger.error("DX describe_connections failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for conn in response.get("connections", []):
        conn_id = conn["connectionId"]
        conn_state = conn.get("connectionState", "")

        if conn_state != "available":
            continue

        # DX ARN 구성
        owner = conn.get("ownerAccount", "")
        conn_region = conn.get("region", region)
        conn_arn = f"arn:aws:directconnect:{conn_region}:{owner}:dxcon/{conn_id}"

        tags = _get_tags(client, conn_arn)
        if tags.get("Monitoring", "").lower() != "on":
            continue

        resources.append(
            ResourceInfo(
                id=conn_id,
                type="DX",
                tags=tags,
                region=region,
            )
        )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 Direct Connect 연결 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/DX):
    - ConnectionState (Minimum) → 'ConnectionState'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "ConnectionId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/DX", "ConnectionState", dim,
                    start_time, end_time, "ConnectionState", metrics, "Minimum")

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """Direct Connect 연결 존재 여부 확인."""
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for DX %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(dx_client, connection_arn: str) -> dict:
    """DX describe_tags 래퍼. DX는 lowercase key 사용: {key: ..., value: ...}."""
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
