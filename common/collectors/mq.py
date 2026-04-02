"""
MQCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 Amazon MQ 브로커 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/AmazonMQ, 디멘션: Broker.
"""

import functools
import logging
import re
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_mq_client():
    """MQ 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("mq")


def _broker_instance_ids(broker_name: str, deployment_mode: str) -> list[str]:
    """DeploymentMode에 따라 CW 디멘션 값 목록 반환.

    SINGLE_INSTANCE: ["{name}-1"]
    ACTIVE_STANDBY_MULTI_AZ: ["{name}-1", "{name}-2"]
    """
    if deployment_mode == "ACTIVE_STANDBY_MULTI_AZ":
        return [f"{broker_name}-1", f"{broker_name}-2"]
    return [f"{broker_name}-1"]


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 Amazon MQ 브로커 목록 반환.

    DeploymentMode에 따라 인스턴스별 ResourceInfo를 생성한다.
    CW 디멘션 값은 {BrokerName}-{index} 형식이므로 id에 반영한다.
    """
    try:
        client = _get_mq_client()
        paginator = client.get_paginator("list_brokers")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("MQ list_brokers failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for broker_summary in page.get("BrokerSummaries", []):
            broker_id = broker_summary["BrokerId"]
            broker_name = broker_summary["BrokerName"]

            tags = _get_tags(client, broker_id)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            deployment_mode = _get_deployment_mode(client, broker_id)
            instance_ids = _broker_instance_ids(broker_name, deployment_mode)

            for instance_id in instance_ids:
                instance_tags = dict(tags)
                instance_tags["Name"] = broker_name
                resources.append(
                    ResourceInfo(
                        id=instance_id,
                        type="MQ",
                        tags=instance_tags,
                        region=region,
                    )
                )

    return resources


def _get_deployment_mode(mq_client, broker_id: str) -> str:
    """브로커 DeploymentMode 조회. 실패 시 SINGLE_INSTANCE 반환."""
    try:
        response = mq_client.describe_broker(BrokerId=broker_id)
        return response.get("DeploymentMode", "SINGLE_INSTANCE")
    except ClientError as e:
        logger.error("MQ describe_broker (deployment_mode) failed for %s: %s", broker_id, e)
        return "SINGLE_INSTANCE"


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """알람 TagName 집합에서 실제 AWS MQ 브로커가 존재하는 TagName 부분집합 반환.

    TagName은 '{broker_name}-1' 또는 '{broker_name}-2' 형식(CW 디멘션 값).
    suffix를 제거하여 base broker name을 추출한 뒤 list_brokers 결과와 비교한다.
    suffix 패턴에 맞지 않는 TagName은 그대로 broker name으로 비교한다.
    """
    if not tag_names:
        return set()

    client = _get_mq_client()
    broker_names: set[str] = set()
    try:
        paginator = client.get_paginator("list_brokers")
        for page in paginator.paginate():
            for b in page.get("BrokerSummaries", []):
                broker_names.add(b["BrokerName"])
    except ClientError as e:
        logger.error("MQ list_brokers failed: %s", e)
        return set()

    alive: set[str] = set()
    for tag_name in tag_names:
        m = re.match(r"^(.+)-([12])$", tag_name)
        if m:
            base_name = m.group(1)
        else:
            base_name = tag_name
        if base_name in broker_names:
            alive.add(tag_name)

    return alive


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 MQ 브로커 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/AmazonMQ, stat: Average):
    - CpuUtilization → 'MqCPU'
    - HeapUsage → 'HeapUsage'
    - JobSchedulerStorePercentUsage → 'JobSchedulerStoreUsage'
    - StorePercentUsage → 'StoreUsage'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "Broker", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/AmazonMQ", "CpuUtilization", dim,
                    start_time, end_time, "MqCPU", metrics)
    _collect_metric("AWS/AmazonMQ", "HeapUsage", dim,
                    start_time, end_time, "HeapUsage", metrics)
    _collect_metric("AWS/AmazonMQ", "JobSchedulerStorePercentUsage", dim,
                    start_time, end_time, "JobSchedulerStoreUsage", metrics)
    _collect_metric("AWS/AmazonMQ", "StorePercentUsage", dim,
                    start_time, end_time, "StoreUsage", metrics)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_AVG)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for MQ %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(mq_client, broker_id: str) -> dict:
    """MQ describe_broker 태그 조회 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not broker_id:
        return {}
    try:
        response = mq_client.describe_broker(BrokerId=broker_id)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("MQ describe_broker failed for %s: %s", broker_id, e)
        return {}
