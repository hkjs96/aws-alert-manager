"""
Amazon MQ 수집기 — 나열은 범용(태그 캐시), 여기엔 인스턴스 분기·describe 폴백·존재 확인만 (docs/specs/resource-type-registry P3)

CW 디멘션 Broker 값은 `{BrokerName}-{1|2}`(DeploymentMode에 따라 1개 또는 2개)라 TagName도 그 형식이다. 브로커 하나가 ResourceInfo
여러 개가 되고 DeploymentMode는 describe_broker가 필요하므로 ARN→TagName 규칙(`identity`)이 아니라 이 모듈의 `_identities`가 맡는다.
메트릭은 스펙(`common/resource_types/mq.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/AmazonMQ.
"""

import functools
import logging
import re

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.mq import SPEC

logger = logging.getLogger(__name__)


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


def _instances(broker_id: str, broker_name: str, tags: dict) -> list[tuple[str, dict]]:
    """브로커 하나 → 인스턴스별 (TagName, tags). Name 태그에 브로커 이름을 넣어 알람 이름에 드러낸다."""
    deployment_mode = _get_deployment_mode(_get_mq_client(), broker_id)
    out: list[tuple[str, dict]] = []
    for instance_id in _broker_instance_ids(broker_name, deployment_mode):
        instance_tags = dict(tags)
        instance_tags["Name"] = broker_name
        out.append((instance_id, instance_tags))
    return out


def _identities(arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로: ARN `arn:aws:mq:<region>:<account>:broker:<name>:<broker-id>` → 인스턴스별 TagName."""
    _prefix, broker_name, broker_id = arn.rsplit(":", 2)
    return _instances(broker_id, broker_name, tags)


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_brokers → 브로커마다 describe_broker(태그) → Monitoring=on만 describe_broker(배포 모드)."""
    try:
        client = _get_mq_client()
        paginator = client.get_paginator("list_brokers")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("MQ list_brokers failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for broker_summary in page.get("BrokerSummaries", []):
            broker_id = broker_summary["BrokerId"]
            broker_name = broker_summary["BrokerName"]
            tags = _get_tags(client, broker_id)
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 배포 모드 describe를 아낀다 — 범용 수집기가 같은 필터를 다시 건다
            found.extend(_instances(broker_id, broker_name, tags))
    return found


def _get_deployment_mode(mq_client, broker_id: str) -> str:
    """브로커 DeploymentMode 조회. 실패 시 SINGLE_INSTANCE 반환."""
    try:
        response = mq_client.describe_broker(BrokerId=broker_id)
        return response.get("DeploymentMode", "SINGLE_INSTANCE")
    except ClientError as e:
        logger.error("MQ describe_broker (deployment_mode) failed for %s: %s", broker_id, e)
        return "SINGLE_INSTANCE"


def _alive(tag_names: set[str]) -> set[str]:
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
        base_name = m.group(1) if m else tag_name
        if base_name in broker_names:
            alive.add(tag_name)
    return alive


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


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
