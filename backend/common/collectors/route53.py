"""
Route 53 상태 검사 수집기 — 글로벌 서비스라 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

RGT는 리전 API이고 Route 53 리소스는 us-east-1에만 나온다. 수집기 단계의 캐시는 실행 리전으로 프라임되므로 다른 리전에서 돌면
빈 결과를 "0개"로 오판한다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`(글로벌 list_health_checks)가 유일한 나열이다.
TagName = HealthCheckId. 메트릭은 스펙(`common/resource_types/route53.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/Route53.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.route53 import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_route53_client():
    """Route53 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("route53")


def _enumerate() -> list[tuple[str, dict]]:
    """list_health_checks 후 검사마다 list_tags_for_resource(N+1). (health_check_id, tags)."""
    try:
        client = _get_route53_client()
        paginator = client.get_paginator("list_health_checks")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Route53 list_health_checks failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for hc in page.get("HealthChecks", []):
            hc_id = hc["Id"]
            found.append((hc_id, _get_tags(client, hc_id)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """Route53 Health Check 존재 여부 확인 — get_health_check."""
    client = _get_route53_client()
    alive: set[str] = set()
    for hc_id in tag_names:
        try:
            client.get_health_check(HealthCheckId=hc_id)
            alive.add(hc_id)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchHealthCheck":
                logger.info("Route53 health check not found (orphan): %s", hc_id)
            else:
                logger.error("get_health_check failed for %s: %s", hc_id, e)
    return alive


def _get_tags(route53_client, health_check_id: str) -> dict:
    """Route53 list_tags_for_resource 래퍼. ClientError 시 빈 dict 반환."""
    try:
        response = route53_client.list_tags_for_resource(ResourceType="healthcheck", ResourceId=health_check_id)
        tag_set = response.get("ResourceTagSet", {})
        return {t["Key"]: t["Value"] for t in tag_set.get("Tags", [])}
    except ClientError as e:
        logger.error("Route53 list_tags_for_resource failed for %s: %s", health_check_id, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
