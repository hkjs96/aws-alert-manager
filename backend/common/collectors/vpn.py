"""
Site-to-Site VPN 수집기 — EC2 서버 측 태그 필터로 나열하므로 태그 캐시(RGT)가 필요 없다 (docs/specs/resource-type-registry P3)

`describe_vpn_connections(Filters=tag:Monitoring=on)`이 서버에서 걸러 주고 응답에 Tags가 있어 N+1이 없다 — EC2 하위 리소스는 RGT
프라임에서 빠져 있고(스펙 notes) 스펙에 `identity`가 없다. deleting/deleted는 제외. TagName = VpnConnectionId.
메트릭은 스펙(`common/resource_types/vpn.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/VPN, 디멘션 VpnId.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.vpn import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    """EC2 클라이언트 싱글턴 (VPN은 EC2 API). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ec2")


def _enumerate() -> list[tuple[str, dict]]:
    """describe_vpn_connections(Filters=tag:Monitoring=on) → 미삭제 (vpn_id, tags)."""
    try:
        client = _get_ec2_client()
        response = client.describe_vpn_connections(Filters=[{"Name": "tag:Monitoring", "Values": ["on"]}])
    except ClientError as e:
        logger.error("EC2 describe_vpn_connections failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for vpn in response.get("VpnConnections", []):
        vpn_id = vpn["VpnConnectionId"]
        state = vpn.get("State", "")
        if state in ("deleting", "deleted"):
            logger.info("Skipping VPN %s: state=%s", vpn_id, state)
            continue
        found.append((vpn_id, {t["Key"]: t["Value"] for t in vpn.get("Tags", [])}))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """VPN Connection 존재 여부 확인 — describe_vpn_connections(VpnConnectionIds), deleted/deleting 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    try:
        resp = ec2.describe_vpn_connections(VpnConnectionIds=list(tag_names))
        for vpn in resp.get("VpnConnections", []):
            if vpn.get("State", "") not in ("deleted", "deleting"):
                alive.add(vpn["VpnConnectionId"])
    except ClientError as e:
        logger.error("describe_vpn_connections failed: %s", e)
    return alive


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
