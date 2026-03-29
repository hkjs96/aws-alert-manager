"""
NATGatewayCollector - Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6

Monitoring=on 태그가 있는 NAT Gateway 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/NATGateway, 디멘션: NatGatewayId.
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
def _get_ec2_client():
    """EC2 클라이언트 싱글턴 (NAT GW는 EC2 API). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ec2")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 NAT Gateway 목록 반환.

    describe_nat_gateways Filter로 tag:Monitoring=on 필터링.
    삭제 중(deleting) 또는 삭제된(deleted) NAT Gateway는 제외하고 로그 기록.
    """
    try:
        client = _get_ec2_client()
        paginator = client.get_paginator("describe_nat_gateways")
        pages = paginator.paginate(
            Filter=[{"Name": "tag:Monitoring", "Values": ["on"]}]
        )
    except ClientError as e:
        logger.error("EC2 describe_nat_gateways failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    for page in pages:
        for natgw in page.get("NatGateways", []):
            natgw_id = natgw["NatGatewayId"]
            state = natgw.get("State", "")

            if state in ("deleting", "deleted"):
                logger.info("Skipping NAT Gateway %s: state=%s", natgw_id, state)
                continue

            tags = {t["Key"]: t["Value"] for t in natgw.get("Tags", [])}
            region = boto3.session.Session().region_name or "us-east-1"

            resources.append(
                ResourceInfo(
                    id=natgw_id,
                    type="NATGateway",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 NAT Gateway 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/NATGateway, stat: Sum):
    - PacketsDropCount → 'PacketsDropCount'
    - ErrorPortAllocation → 'ErrorPortAllocation'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "NatGatewayId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/NATGateway", "PacketsDropCount", dim, start_time, end_time,
                    "PacketsDropCount", metrics)
    _collect_metric("AWS/NATGateway", "ErrorPortAllocation", dim, start_time, end_time,
                    "ErrorPortAllocation", metrics)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_SUM)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for NATGateway %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")
