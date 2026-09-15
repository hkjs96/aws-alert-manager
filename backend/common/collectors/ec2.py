"""
EC2 수집기 — 나열은 EC2 서버 측 태그 필터, 메트릭은 타입 고유 조회(오버라이드) (docs/specs/resource-type-registry P3)

나열: `describe_instances(Filters=tag:Monitoring=on)`이 서버에서 걸러 주고 응답에 Tags가 있어 N+1이 없다 — EC2 하위 리소스는 RGT
프라임에서 빠져 있고 스펙에 `identity`가 없다. terminated/shutting-down은 제외. TagName = InstanceId.
메트릭(오버라이드 `_metrics`): 정의로 표현되지 않는 것이 있다 — CWAgent 메모리(`Threshold_Memory` 태그가 있을 때만)와 디스크
(`Threshold_Disk_*` 태그의 경로마다 list_metrics로 device/fstype 디멘션을 **발견**해야 한다, 정의의 dynamic_dimensions). 결과 키
`CPU`·`Memory`·`Disk_<suffix>`는 tag_resolver·daily_monitor의 임계치 분기와 묶여 있어 그대로 둔다.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, run_memo
from common.collectors.generic import GenericCollector
from common.resource_types.ec2 import SPEC
from common.tag_resolver import get_disk_thresholds

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    """EC2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ec2")


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    """CloudWatch 클라이언트 싱글턴 (disk list_metrics 용). 테스트 시 cache_clear()로 리셋."""
    return boto3.client("cloudwatch")


def _enumerate() -> list[tuple[str, dict]]:
    """describe_instances(Filters=tag:Monitoring=on) 전 페이지 → 미종료 (instance_id, tags).

    describe_instances는 결과가 많으면 여러 페이지로 나뉜다. 페이지네이션 없이 첫 페이지만 읽으면 나머지 인스턴스가
    조용히 누락되어(알람 미생성 + 메트릭 미점검) 기존 알람이 고아로 오판될 수 있다.
    """
    try:
        ec2 = _get_ec2_client()
        paginator = ec2.get_paginator("describe_instances")
        pages = list(paginator.paginate(Filters=[{"Name": "tag:Monitoring", "Values": ["on"]}]))
    except ClientError as e:
        logger.error("EC2 describe_instances failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = instance["InstanceId"]
                state = instance.get("State", {}).get("Name", "")
                if state in ("terminated", "shutting-down"):
                    logger.info("Skipping EC2 instance %s: state=%s", instance_id, state)
                    continue
                found.append((instance_id, {t["Key"]: t["Value"] for t in instance.get("Tags", [])}))
    return found


def _metrics(instance_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 EC2 메트릭 조회.

    수집 메트릭:
    - CPUUtilization (AWS/EC2) - 항상 조회
    - mem_used_percent (CWAgent) - 태그에 Threshold_Memory 있을 때만
    - disk_used_percent (CWAgent) - 태그에 Threshold_Disk_* 있을 때만

    데이터 없거나 InsufficientData이면 해당 메트릭 skip (None 반환은 모든 메트릭 없을 때).
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)
    metrics: dict[str, float] = {}

    # 1. CPUUtilization (AWS/EC2) - 항상 조회
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
            logger.info("Skipping Memory metric for %s: no CWAgent data", instance_id)

    # 3. disk_used_percent (CWAgent) - Threshold_Disk_* 태그 있을 때만
    disk_thresholds = get_disk_thresholds(resource_tags)
    for path in disk_thresholds:
        disk = _query_disk_metric(instance_id, path, start_time, end_time)
        if disk is not None:
            from common.tag_resolver import disk_path_to_tag_suffix
            suffix = disk_path_to_tag_suffix(path)
            metrics[f"Disk_{suffix}"] = disk
        else:
            logger.info("Skipping Disk metric for %s path=%s: no CWAgent data", instance_id, path)

    return metrics if metrics else None


def _alive(tag_names: set[str]) -> set[str]:
    """EC2 인스턴스 존재 여부 확인. terminated/shutting-down 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    id_list = list(tag_names)
    for i in range(0, len(id_list), 200):
        batch = id_list[i:i + 200]
        try:
            resp = ec2.describe_instances(InstanceIds=batch)
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    state = inst.get("State", {}).get("Name", "")
                    if state not in ("terminated", "shutting-down"):
                        alive.add(inst["InstanceId"])
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "InvalidInstanceID.NotFound":
                # 배치에 없는 ID가 하나라도 있으면 전체가 실패 → 개별 확인
                _check_individually(ec2, batch, alive)
            else:
                logger.error("describe_instances failed: %s", e)
    return alive


def _check_individually(ec2, batch: list[str], alive: set[str]) -> None:
    """배치 조회 실패 시 개별 인스턴스 확인."""
    for iid in batch:
        try:
            resp = ec2.describe_instances(InstanceIds=[iid])
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    state = inst.get("State", {}).get("Name", "")
                    if state not in ("terminated", "shutting-down"):
                        alive.add(inst["InstanceId"])
        except ClientError:
            pass  # 완전히 없는 인스턴스 → alive에 추가 안 함


def _query_disk_metric(instance_id: str, path: str, start_time: datetime, end_time: datetime) -> float | None:
    """CWAgent disk_used_percent 메트릭 조회. path 기준으로 필터링."""
    try:
        cw = _get_cw_client()
        # CWAgent disk 메트릭은 path, device, fstype Dimension이 필요하므로
        # list_metrics로 해당 인스턴스+경로의 실제 Dimension 조회 후 사용.
        response = run_memo(
            ("disk_list_metrics", instance_id, path),
            lambda: cw.list_metrics(
                Namespace="CWAgent",
                MetricName="disk_used_percent",
                Dimensions=[
                    {"Name": "InstanceId", "Value": instance_id},
                    {"Name": "path", "Value": path},
                ],
            ),
        )
        metric_list = response.get("Metrics", [])
        if not metric_list:
            return None
        dimensions = metric_list[0]["Dimensions"]
        return query_metric("CWAgent", "disk_used_percent", dimensions, start_time, end_time)
    except ClientError as e:
        logger.error("CloudWatch list_metrics failed for disk path=%s instance=%s: %s", path, instance_id, e)
        return None


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, metrics=_metrics)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
