"""
CloudFront 수집기 — 글로벌 서비스라 나열은 describe, 메트릭은 us-east-1 전용 클라이언트(오버라이드) (docs/specs/resource-type-registry P3)

나열: RGT는 리전 API이고 CloudFront 배포는 us-east-1에만 나오므로 실행 리전 캐시로 나열하면 0개로 오판한다 — 스펙에 `identity`가
없고 이 모듈의 `_enumerate`(list_distributions)가 유일한 나열이다(태그는 캐시 **히트만** 믿는다). TagName = 배포 ID.
메트릭(오버라이드 `_metrics`): AWS/CloudFront 지표는 us-east-1에만 발행되어 기본 리전 CloudWatch 클라이언트(`collect_metric`)로는
읽을 수 없다 — 전용 클라이언트로 직접 get_metric_statistics를 부른다(메트릭 배치도 타지 않는다).
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.base import CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM
from common.collectors.generic import GenericCollector
from common.resource_types.cloudfront import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_cloudfront_client():
    """CloudFront 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("cloudfront")


@functools.lru_cache(maxsize=None)
def _get_cw_client_us_east_1():
    """us-east-1 CloudWatch 클라이언트 싱글턴. CloudFront 메트릭 전용."""
    return boto3.client("cloudwatch", region_name="us-east-1")


def _enumerate() -> list[tuple[str, dict]]:
    """list_distributions 후 배포마다 list_tags_for_resource(캐시 히트 우선). (distribution_id, tags).

    CloudFront Tags 응답: {"Tags": {"Items": [{"Key": ..., "Value": ...}]}}
    """
    try:
        client = _get_cloudfront_client()
        paginator = client.get_paginator("list_distributions")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("CloudFront list_distributions failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for dist in page.get("DistributionList", {}).get("Items", []):
            found.append((dist["Id"], _get_tags(client, dist["ARN"])))
    return found


def _metrics(resource_id: str, resource_tags: dict | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 CloudFront 배포 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/CloudFront, us-east-1 고정):
    - 5xxErrorRate (Average) → 'CF5xxErrorRate'
    - 4xxErrorRate (Average) → 'CF4xxErrorRate'
    - Requests (Sum) → 'CFRequests'
    - BytesDownloaded (Sum) → 'CFBytesDownloaded'
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "DistributionId", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/CloudFront", "5xxErrorRate", dim, start_time, end_time, "CF5xxErrorRate", metrics, CW_STAT_AVG)
    _collect_metric("AWS/CloudFront", "4xxErrorRate", dim, start_time, end_time, "CF4xxErrorRate", metrics, CW_STAT_AVG)
    _collect_metric("AWS/CloudFront", "Requests", dim, start_time, end_time, "CFRequests", metrics, CW_STAT_SUM)
    _collect_metric("AWS/CloudFront", "BytesDownloaded", dim, start_time, end_time, "CFBytesDownloaded", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def _alive(tag_names: set[str]) -> set[str]:
    """CloudFront 배포 존재 여부 확인 — list_distributions 전체와 교집합."""
    client = _get_cloudfront_client()
    alive: set[str] = set()
    try:
        paginator = client.get_paginator("list_distributions")
        existing_ids: set[str] = set()
        for page in paginator.paginate():
            for dist in page.get("DistributionList", {}).get("Items", []):
                existing_ids.add(dist["Id"])
    except ClientError as e:
        logger.error("CloudFront list_distributions failed: %s", e)
        return alive

    for dist_id in tag_names:
        if dist_id in existing_ids:
            alive.add(dist_id)
        else:
            logger.info("CloudFront distribution not found (orphan): %s", dist_id)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions, start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 (us-east-1 CW 클라이언트 사용). 데이터 없으면 skip + info 로그."""
    cw = _get_cw_client_us_east_1()
    try:
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=cw_metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=[stat],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            logger.info("Skipping %s metric for CloudFront %s: no data",
                        result_key, dimensions[0]["Value"] if dimensions else "unknown")
            return
        latest = max(datapoints, key=lambda d: d["Timestamp"])
        metrics_dict[result_key] = latest[stat]
    except ClientError as e:
        logger.error("CloudWatch query failed for %s/%s: %s", namespace, cw_metric_name, e)


def _get_tags(cf_client, distribution_arn: str) -> dict:
    """CloudFront list_tags_for_resource 래퍼. 응답 형식: {"Tags": {"Items": [{"Key": ..., "Value": ...}]}}"""
    cached = cached_tags(distribution_arn, trust_negative=False)
    if cached is not None:
        return cached
    try:
        response = cf_client.list_tags_for_resource(Resource=distribution_arn)
        items = response.get("Tags", {}).get("Items", [])
        return {t["Key"]: t["Value"] for t in items}
    except ClientError as e:
        logger.error("CloudFront list_tags_for_resource failed for %s: %s", distribution_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, metrics=_metrics)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
