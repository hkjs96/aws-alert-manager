"""
VPNCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 VPN Connection 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/VPN, 디멘션: VpnId.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES

logger = logging.getLogger(__name__)

CW_STAT_MAX = "Maximum"


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    """EC2 클라이언트 싱글턴 (VPN은 EC2 API). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ec2")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 VPN Connection 목록 반환.

    describe_vpn_connections Filter로 tag:Monitoring=on 필터링.
    삭제 중(deleting) 또는 삭제된(deleted) VPN은 제외하고 로그 기록.
    """
    try:
        client = _get_ec2_client()
        response = client.describe_vpn_connections(
            Filters=[{"Name": "tag:Monitoring", "Values": ["on"]}]
        )
    except ClientError as e:
        logger.error("EC2 describe_vpn_connections failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for vpn in response.get("VpnConnections", []):
        vpn_id = vpn["VpnConnectionId"]
        state = vpn.get("State", "")

        if state in ("deleting", "deleted"):
            logger.info("Skipping VPN %s: state=%s", vpn_id, state)
            continue

        tags = {t["Key"]: t["Value"] for t in vpn.get("Tags", [])}

        resources.append(
            ResourceInfo(
                id=vpn_id,
                type="VPN",
                tags=tags,
                region=region,
            )
        )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 VPN 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/VPN):
    - TunnelState (Maximum) → 'TunnelState'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "VpnId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/VPN", "TunnelState", dim,
                    start_time, end_time, "TunnelState", metrics)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """VPN Connection 존재 여부 확인. deleted/deleting 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    try:
        resp = ec2.describe_vpn_connections(
            VpnConnectionIds=list(tag_names),
        )
        for vpn in resp.get("VpnConnections", []):
            state = vpn.get("State", "")
            if state not in ("deleted", "deleting"):
                alive.add(vpn["VpnConnectionId"])
    except ClientError as e:
        logger.error("describe_vpn_connections failed: %s", e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_MAX)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for VPN %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")
