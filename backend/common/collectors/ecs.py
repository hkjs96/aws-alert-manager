"""
ECS 수집기 — 클러스터·launchType이 describe를 요구하므로 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

CloudWatch 복합 디멘션 ClusterName + ServiceName. 구 형식 서비스 ARN(`service/<name>`)엔 클러스터가 없고 `_ecs_launch_type`엔
describe_services가 필요해 RGT 나열로 아낄 콜이 없다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다
(태그는 캐시에서 읽는다). TagName = 서비스 이름. ECS 태그 API는 lowercase key/value를 쓴다.
메트릭은 스펙(`common/resource_types/ecs.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/ECS.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.ecs import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_ecs_client():
    """ECS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("ecs")


def _enumerate() -> list[tuple[str, dict]]:
    """list_clusters → list_services → describe_services 배치 → 태그. (service_name, tags + _ecs_launch_type/_cluster_name)."""
    client = _get_ecs_client()
    try:
        cluster_paginator = client.get_paginator("list_clusters")
        cluster_pages = cluster_paginator.paginate()
    except ClientError as e:
        logger.error("ECS list_clusters failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for cluster_page in cluster_pages:
        for cluster_arn in cluster_page.get("clusterArns", []):
            cluster_name = cluster_arn.rsplit("/", 1)[-1]
            found.extend(_services_for_cluster(client, cluster_arn, cluster_name))
    return found


def _services_for_cluster(client, cluster_arn: str, cluster_name: str) -> list[tuple[str, dict]]:
    """단일 클러스터의 서비스 (service_name, tags). 실패한 클러스터는 로그 후 빈 목록."""
    try:
        svc_paginator = client.get_paginator("list_services")
        svc_pages = svc_paginator.paginate(cluster=cluster_arn)
    except ClientError as e:
        logger.error("ECS list_services failed for %s: %s", cluster_arn, e)
        return []

    found: list[tuple[str, dict]] = []
    for svc_page in svc_pages:
        svc_arns = svc_page.get("serviceArns", [])
        if not svc_arns:
            continue
        try:
            desc_resp = client.describe_services(cluster=cluster_arn, services=svc_arns)
        except ClientError as e:
            logger.error("ECS describe_services failed for %s: %s", cluster_arn, e)
            continue

        for svc in desc_resp.get("services", []):
            tags = _get_tags(client, svc.get("serviceArn", ""))
            tags["_ecs_launch_type"] = svc.get("launchType", "")
            tags["_cluster_name"] = cluster_name
            found.append((svc.get("serviceName", ""), tags))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """ECS 서비스 존재 여부 확인 — 전 클러스터 list_services와 교집합."""
    client = _get_ecs_client()
    alive: set[str] = set()
    try:
        cluster_paginator = client.get_paginator("list_clusters")
        cluster_pages = cluster_paginator.paginate()
    except ClientError as e:
        logger.error("ECS list_clusters failed: %s", e)
        return alive

    all_service_names: set[str] = set()
    for cluster_page in cluster_pages:
        for cluster_arn in cluster_page.get("clusterArns", []):
            try:
                svc_paginator = client.get_paginator("list_services")
                for svc_page in svc_paginator.paginate(cluster=cluster_arn):
                    for svc_arn in svc_page.get("serviceArns", []):
                        all_service_names.add(svc_arn.rsplit("/", 1)[-1])
            except ClientError as e:
                logger.error("ECS list_services failed for %s: %s", cluster_arn, e)

    for name in tag_names:
        if name in all_service_names:
            alive.add(name)
        else:
            logger.info("ECS service not found (orphan): %s", name)
    return alive


def _get_tags(ecs_client, resource_arn: str) -> dict:
    """ECS list_tags_for_resource 래퍼. lowercase key/value → 표준 dict 변환."""
    cached = cached_tags(resource_arn)
    if cached is not None:
        return cached
    if not resource_arn:
        return {}
    try:
        response = ecs_client.list_tags_for_resource(resourceArn=resource_arn)
        return {t["key"]: t["value"] for t in response.get("tags", [])}
    except ClientError as e:
        logger.error("ECS list_tags_for_resource failed for %s: %s", resource_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
