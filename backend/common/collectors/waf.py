"""
WAFv2 수집기 — 나열은 범용(태그 캐시), 여기엔 REGIONAL 판별·내부 태그·describe 폴백·존재 확인만 (docs/specs/resource-type-registry P3)

옛 수집기는 REGIONAL 스코프만 나열했다(CLOUDFRONT 스코프는 us-east-1 조회가 필요 — 미구현, 스펙 notes). ARN 리소스 부분이
`regional/webacl/<name>/<id>`인 것만 대상이라 스펙 `identity` 대신 이 모듈의 `_identities`가 가른다(`global/webacl/…`은 건너뜀).
TagName = WebACL 이름. 내부 태그 `_waf_rule=ALL`·`_waf_region=<리전>`은 알람·메트릭의 Rule·Region 디멘션이 된다.
메트릭은 스펙(`common/resource_types/waf.py`)의 알람 정의에서 만든다 — 디멘션은 알람과 같은 빌더라 WebACL+Rule+Region(옛 수집기는
Region을 빼고 물어 데이터가 없었다; docs/specs/resource-type-registry tasks 3.4). 네임스페이스 AWS/WAFV2.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector, session_region
from common.resource_types.waf import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_wafv2_client():
    """WAFv2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("wafv2")


def _with_internal_tags(tags: dict, region: str) -> dict:
    acl_tags = dict(tags)
    acl_tags["_waf_rule"] = "ALL"
    acl_tags["_waf_region"] = region
    return acl_tags


def _identities(arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로: `…:regional/webacl/<name>/<id>` → (이름, 태그 + 내부 태그). CLOUDFRONT 스코프(`global/…`)는 옛 수집기처럼 제외."""
    resource = arn.split(":", 5)[-1]
    parts = resource.split("/")
    if len(parts) != 4 or parts[0] != "regional" or parts[1] != "webacl":
        return []
    return [(parts[2], _with_internal_tags(tags, session_region()))]


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_web_acls(Scope=REGIONAL) 후 ACL마다 list_tags_for_resource(N+1). (acl_name, tags + 내부 태그)."""
    client = _get_wafv2_client()
    region = session_region()
    try:
        response = client.list_web_acls(Scope="REGIONAL")
    except ClientError as e:
        logger.error("WAFv2 list_web_acls failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for acl in response.get("WebACLs", []):
        tags = _get_tags(client, acl.get("ARN", ""))
        found.append((acl.get("Name", ""), _with_internal_tags(tags, region)))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """WAFv2 WebACL 존재 여부 확인 — list_web_acls(REGIONAL) 이름과 교집합."""
    client = _get_wafv2_client()
    alive: set[str] = set()
    try:
        response = client.list_web_acls(Scope="REGIONAL")
    except ClientError as e:
        logger.error("WAFv2 list_web_acls failed: %s", e)
        return alive

    existing_names = {acl["Name"] for acl in response.get("WebACLs", [])}
    for name in tag_names:
        if name in existing_names:
            alive.add(name)
        else:
            logger.info("WAF WebACL not found (orphan): %s", name)
    return alive


def _get_tags(wafv2_client, resource_arn: str) -> dict:
    """WAFv2 list_tags_for_resource 래퍼. TagInfoForResource.TagList 구조 파싱."""
    cached = cached_tags(resource_arn)
    if cached is not None:
        return cached
    if not resource_arn:
        return {}
    try:
        response = wafv2_client.list_tags_for_resource(ResourceARN=resource_arn)
        tag_list = response.get("TagInfoForResource", {}).get("TagList", [])
        return {t["Key"]: t["Value"] for t in tag_list}
    except ClientError as e:
        logger.error("WAFv2 list_tags_for_resource failed for %s: %s", resource_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
