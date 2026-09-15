"""
Classic Load Balancer 수집기 — 나열은 범용(태그 캐시), 여기엔 classic 판별·describe 폴백·존재 확인만 (docs/specs/resource-type-registry P3)

RGT 필터 `elasticloadbalancing:loadbalancer`는 ALB/NLB와 공유한다 — ARN 리소스 부분이 `loadbalancer/<name>`(app/·net/·gwy/ 접두 없음)인
것만 classic이라 스펙 `identity` 대신 이 모듈의 `_identities`가 가른다. TagName = LoadBalancerName. describe 폴백은 describe_tags N+1
(classic ELB 태그 API는 캐시 ARN을 모른다). 메트릭은 스펙(`common/resource_types/clb.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/ELB.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.clb import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_elb_client():
    """Classic ELB 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elb")


def _identities(arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로: `…:loadbalancer/<name>`만 classic — `loadbalancer/app|net|gwy/…`는 ALB/NLB/GWLB(elb 수집기 몫)."""
    _prefix, _, rest = arn.partition(":loadbalancer/")
    if not rest or "/" in rest:
        return []
    return [(rest, tags)]


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: describe_load_balancers 후 LB마다 describe_tags(N+1). (lb_name, tags)."""
    try:
        client = _get_elb_client()
        paginator = client.get_paginator("describe_load_balancers")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("ELB describe_load_balancers failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for lb in page.get("LoadBalancerDescriptions", []):
            lb_name = lb["LoadBalancerName"]
            found.append((lb_name, _get_tags(client, lb_name)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """Classic Load Balancer 존재 여부 확인 — describe_load_balancers(LoadBalancerNames)."""
    client = _get_elb_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.describe_load_balancers(LoadBalancerNames=[name])
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("LoadBalancerNotFound", "AccessPointNotFound"):
                logger.info("CLB not found (orphan): %s", name)
            else:
                logger.error("describe_load_balancers failed for %s: %s", name, e)
    return alive


def _get_tags(elb_client, lb_name: str) -> dict:
    """Classic ELB describe_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not lb_name:
        return {}
    try:
        response = elb_client.describe_tags(LoadBalancerNames=[lb_name])
        descriptions = response.get("TagDescriptions", [])
        if not descriptions:
            return {}
        return {t["Key"]: t["Value"] for t in descriptions[0].get("Tags", [])}
    except ClientError as e:
        logger.error("ELB describe_tags failed for %s: %s", lb_name, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
