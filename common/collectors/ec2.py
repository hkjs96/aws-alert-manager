"""
EC2Collector - Requirements 1.1, 1.2, 1.5, 3.5

Monitoring=on 태그가 있는 EC2 인스턴스 수집 및 CloudWatch 메트릭 조회.
CWAgent 메트릭(Memory, Disk)은 데이터 없으면 skip.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES
from common.tag_resolver import get_disk_thresholds

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    """EC2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ec2")


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    """CloudWatch 클라이언트 싱글턴 (disk list_metrics 용). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("cloudwatch")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 EC2 인스턴스 목록 반환.
    terminated/shutting-down 상태 인스턴스는 제외하고 로그 기록.

    Returns:
        ResourceInfo 딕셔너리 리스트
    """
    try:
        ec2 = _get_ec2_client()
        response = ec2.describe_instances(
            Filters=[{"Name": "tag:Monitoring", "Values": ["on"]}]
        )
    except ClientError as e:
        logger.error("EC2 describe_instances failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            instance_id = instance["InstanceId"]
            state = instance.get("State", {}).get("Name", "")

            # terminated / shutting-down 제외
            if state in ("terminated", "shutting-down"):
                logger.info(
                    "Skipping EC2 instance %s: state=%s", instance_id, state
                )
                continue

            tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
            region = boto3.session.Session().region_name or "us-east-1"

            resources.append(
                ResourceInfo(
                    id=instance_id,
                    type="EC2",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(instance_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 EC2 메트릭 조회.

    수집 메트릭:
    - CPUUtilization (AWS/EC2) - 항상 조회
    - mem_used_percent (CWAgent) - 태그에 Threshold_Memory 있을 때만
    - disk_used_percent (CWAgent) - 태그에 Threshold_Disk_* 있을 때만

    데이터 없거나 InsufficientData이면 해당 메트릭 skip (None 반환은 모든 메트릭 없을 때).

    Args:
        instance_id: EC2 인스턴스 ID
        resource_tags: 리소스 태그 딕셔너리 (CWAgent 메트릭 조회 여부 결정)

    Returns:
        {metric_name: value} 딕셔너리. 수집된 메트릭이 하나도 없으면 None.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    metrics: dict[str, float] = {}

    # 1. CPUUtilization (기본 메트릭)
    cpu = query_metric(
        "AWS/EC2", "CPUUtilization",
        [{"Name": "InstanceId", "Value": instance_id}],
        start_time, end_time,
    )
    if cpu is not None:
        metrics["CPU"] = cpu

    # 2. mem_used_percent (CWAgent) - Threshold_Memory 태그 있을 때만
    if "Threshold_Memory" in resource_tags:
        mem = query_metric(
            "CWAgent", "mem_used_percent",
            [{"Name": "InstanceId", "Value": instance_id}],
            start_time, end_time,
        )
        if mem is not None:
            metrics["Memory"] = mem
        else:
            logger.info(
                "Skipping Memory metric for %s: no CWAgent data", instance_id
            )

    # 3. disk_used_percent (CWAgent) - Threshold_Disk_* 태그 있을 때만
    disk_thresholds = get_disk_thresholds(resource_tags)
    for path in disk_thresholds:
        disk = _query_disk_metric(instance_id, path, start_time, end_time)
        if disk is not None:
            from common.tag_resolver import disk_path_to_tag_suffix
            suffix = disk_path_to_tag_suffix(path)
            metrics[f"Disk_{suffix}"] = disk
        else:
            logger.info(
                "Skipping Disk metric for %s path=%s: no CWAgent data",
                instance_id, path,
            )

    return metrics if metrics else None


def _query_disk_metric(
    instance_id: str,
    path: str,
    start_time: datetime,
    end_time: datetime,
) -> float | None:
    """CWAgent disk_used_percent 메트릭 조회. path 기준으로 필터링."""
    try:
        cw = _get_cw_client()
        # CWAgent disk 메트릭은 path, device, fstype Dimension이 필요하므로
        # list_metrics로 해당 인스턴스+경로의 실제 Dimension 조회 후 사용
        response = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[
                {"Name": "InstanceId", "Value": instance_id},
                {"Name": "path", "Value": path},
            ],
        )
        metric_list = response.get("Metrics", [])
        if not metric_list:
            return None

        # 첫 번째 매칭 메트릭의 Dimension으로 조회
        dimensions = metric_list[0]["Dimensions"]
        return query_metric(
            "CWAgent", "disk_used_percent",
            dimensions, start_time, end_time,
        )
    except ClientError as e:
        logger.error(
            "CloudWatch list_metrics failed for disk path=%s instance=%s: %s",
            path, instance_id, e,
        )
        return None
