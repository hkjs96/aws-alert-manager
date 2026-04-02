"""
SageMakerCollector - Extended Resource Monitoring (Compound Dimension)

Monitoring=on 태그가 있는 SageMaker InService 엔드포인트 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/SageMaker, Compound_Dimension: EndpointName + VariantName.
학습 작업(Training Job)은 수집 대상에서 제외.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_sagemaker_client():
    """SageMaker 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sagemaker")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 SageMaker InService 엔드포인트 목록 반환.

    list_endpoints(StatusEquals="InService") paginator → list_tags → Monitoring=on 필터링.
    describe_endpoint → ProductionVariants[0].VariantName → _variant_name Internal_Tag 설정.
    학습 작업(Training Job)은 list_endpoints만 사용하므로 자동 제외.
    """
    client = _get_sagemaker_client()
    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    try:
        paginator = client.get_paginator("list_endpoints")
        pages = paginator.paginate(StatusEquals="InService")
    except ClientError as e:
        logger.error("SageMaker list_endpoints failed: %s", e)
        raise

    for page in pages:
        for ep in page.get("Endpoints", []):
            ep_name = ep.get("EndpointName", "")
            ep_arn = ep.get("EndpointArn", "")
            ep_status = ep.get("EndpointStatus", "")

            # API-level filter + defensive check
            if ep_status != "InService":
                continue

            tags = _get_tags(client, ep_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            variant_name = _get_variant_name(client, ep_name)
            tags["_variant_name"] = variant_name

            resources.append(
                ResourceInfo(
                    id=ep_name,
                    type="SageMaker",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 SageMaker 엔드포인트 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/SageMaker, Compound_Dimension: EndpointName + VariantName):
    - Invocations (Sum) → 'SMInvocations'
    - InvocationErrors (Sum) → 'SMInvocationErrors'
    - ModelLatency (Average) → 'SMModelLatency'
    - CPUUtilization (Average) → 'SMCPU'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    variant_name = resource_tags.get("_variant_name", "")
    dims = [
        {"Name": "EndpointName", "Value": resource_id},
        {"Name": "VariantName", "Value": variant_name},
    ]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/SageMaker", "Invocations", dims,
                    start_time, end_time, "SMInvocations", metrics, CW_STAT_SUM)
    _collect_metric("AWS/SageMaker", "InvocationErrors", dims,
                    start_time, end_time, "SMInvocationErrors", metrics, CW_STAT_SUM)
    _collect_metric("AWS/SageMaker", "ModelLatency", dims,
                    start_time, end_time, "SMModelLatency", metrics, CW_STAT_AVG)
    _collect_metric("AWS/SageMaker", "CPUUtilization", dims,
                    start_time, end_time, "SMCPU", metrics, CW_STAT_AVG)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """SageMaker 엔드포인트 존재 여부 확인."""
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for SageMaker %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(sagemaker_client, resource_arn: str) -> dict:
    """SageMaker list_tags 래퍼. Tags 구조 파싱."""
    if not resource_arn:
        return {}
    try:
        response = sagemaker_client.list_tags(ResourceArn=resource_arn)
        tags = response.get("Tags", [])
        return {t["Key"]: t["Value"] for t in tags}
    except ClientError as e:
        logger.error("SageMaker list_tags failed for %s: %s",
                     resource_arn, e)
        return {}


def _get_variant_name(sagemaker_client, endpoint_name: str) -> str:
    """describe_endpoint → ProductionVariants[0].VariantName 조회."""
    try:
        response = sagemaker_client.describe_endpoint(
            EndpointName=endpoint_name)
        variants = response.get("ProductionVariants", [])
        if variants:
            return variants[0].get("VariantName", "")
        return ""
    except ClientError as e:
        logger.error("SageMaker describe_endpoint failed for %s: %s",
                     endpoint_name, e)
        return ""
