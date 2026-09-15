"""
SageMaker 수집기 — 나열은 범용(태그 캐시), 여기엔 InService 판정·VariantName 내부 태그·describe 폴백·존재 확인만 (docs/specs/resource-type-registry P3)

CloudWatch 복합 디멘션 EndpointName + VariantName. InService 엔드포인트만 대상이고(학습 작업 제외) VariantName은 describe_endpoint의
ProductionVariants[0]에서 온다 — 스펙 `identity` 대신 이 모듈의 `_identities`가 맡는다(Monitoring=on 엔드포인트마다 describe 1회,
옛 경로도 같은 describe를 했다). TagName = 엔드포인트 이름(ARN `endpoint/<name>`).
메트릭은 스펙(`common/resource_types/sagemaker.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/SageMaker.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.sagemaker import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_sagemaker_client():
    """SageMaker 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sagemaker")


def _identities(arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로: ARN `arn:aws:sagemaker:<region>:<account>:endpoint/<name>` → InService면 (이름, 태그 + _variant_name)."""
    ep_name = arn.rsplit("/", 1)[-1]
    try:
        detail = _get_sagemaker_client().describe_endpoint(EndpointName=ep_name)
    except ClientError as e:
        logger.error("SageMaker describe_endpoint failed for %s: %s", ep_name, e)
        return []
    if detail.get("EndpointStatus", "") != "InService":
        return []
    variants = detail.get("ProductionVariants", [])
    ep_tags = dict(tags)
    ep_tags["_variant_name"] = variants[0].get("VariantName", "") if variants else ""
    return [(ep_name, ep_tags)]


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_endpoints(StatusEquals=InService) → list_tags → Monitoring=on만 describe_endpoint(변형 이름)."""
    client = _get_sagemaker_client()
    try:
        paginator = client.get_paginator("list_endpoints")
        pages = paginator.paginate(StatusEquals="InService")
    except ClientError as e:
        logger.error("SageMaker list_endpoints failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for ep in page.get("Endpoints", []):
            ep_name = ep.get("EndpointName", "")
            if ep.get("EndpointStatus", "") != "InService":
                continue
            tags = _get_tags(client, ep.get("EndpointArn", ""))
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 변형 이름 describe를 아낀다 — 범용 수집기가 같은 필터를 다시 건다
            tags["_variant_name"] = _get_variant_name(client, ep_name)
            found.append((ep_name, tags))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """SageMaker 엔드포인트 존재 여부 확인 — describe_endpoint."""
    client = _get_sagemaker_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.describe_endpoint(EndpointName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ValidationException":
                logger.info("SageMaker endpoint not found (orphan): %s", name)
            else:
                logger.error("describe_endpoint failed for %s: %s", name, e)
    return alive


def _get_tags(sagemaker_client, resource_arn: str) -> dict:
    """SageMaker list_tags 래퍼. Tags 구조 파싱."""
    cached = cached_tags(resource_arn)
    if cached is not None:
        return cached
    if not resource_arn:
        return {}
    try:
        response = sagemaker_client.list_tags(ResourceArn=resource_arn)
        return {t["Key"]: t["Value"] for t in response.get("Tags", [])}
    except ClientError as e:
        logger.error("SageMaker list_tags failed for %s: %s", resource_arn, e)
        return {}


def _get_variant_name(sagemaker_client, endpoint_name: str) -> str:
    """describe_endpoint → ProductionVariants[0].VariantName 조회."""
    try:
        response = sagemaker_client.describe_endpoint(EndpointName=endpoint_name)
        variants = response.get("ProductionVariants", [])
        return variants[0].get("VariantName", "") if variants else ""
    except ClientError as e:
        logger.error("SageMaker describe_endpoint failed for %s: %s", endpoint_name, e)
        return ""


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
