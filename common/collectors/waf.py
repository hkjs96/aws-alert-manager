"""
WAFCollector - Extended Resource Monitoring (Compound Dimension)

Monitoring=on 태그가 있는 WAFv2 WebACL 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/WAFV2, Compound_Dimension: WebACL + Rule.
WAFv2 태그는 TagInfoForResource.TagList 구조 사용.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_wafv2_client():
    """WAFv2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("wafv2")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 WAFv2 WebACL 목록 반환.

    list_web_acls(Scope="REGIONAL") → list_tags_for_resource → Monitoring=on 필터링.
    _waf_rule Internal_Tag 기본값 "ALL" 설정.
    """
    client = _get_wafv2_client()
    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    try:
        response = client.list_web_acls(Scope="REGIONAL")
    except ClientError as e:
        logger.error("WAFv2 list_web_acls failed: %s", e)
        raise

    for acl in response.get("WebACLs", []):
        acl_name = acl.get("Name", "")
        acl_arn = acl.get("ARN", "")

        tags = _get_tags(client, acl_arn)
        if tags.get("Monitoring", "").lower() != "on":
            continue

        tags["_waf_rule"] = "ALL"

        resources.append(
            ResourceInfo(
                id=acl_name,
                type="WAF",
                tags=tags,
                region=region,
            )
        )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 WAFv2 WebACL 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/WAFV2, Compound_Dimension: WebACL + Rule):
    - BlockedRequests (Sum) → 'WAFBlockedRequests'
    - AllowedRequests (Sum) → 'WAFAllowedRequests'
    - CountedRequests (Sum) → 'WAFCountedRequests'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    rule = resource_tags.get("_waf_rule", "ALL")
    dims = [
        {"Name": "WebACL", "Value": resource_id},
        {"Name": "Rule", "Value": rule},
    ]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/WAFV2", "BlockedRequests", dims,
                    start_time, end_time, "WAFBlockedRequests", metrics, CW_STAT_SUM)
    _collect_metric("AWS/WAFV2", "AllowedRequests", dims,
                    start_time, end_time, "WAFAllowedRequests", metrics, CW_STAT_SUM)
    _collect_metric("AWS/WAFV2", "CountedRequests", dims,
                    start_time, end_time, "WAFCountedRequests", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """WAFv2 WebACL 존재 여부 확인."""
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for WAF %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(wafv2_client, resource_arn: str) -> dict:
    """WAFv2 list_tags_for_resource 래퍼. TagInfoForResource.TagList 구조 파싱."""
    if not resource_arn:
        return {}
    try:
        response = wafv2_client.list_tags_for_resource(ResourceARN=resource_arn)
        tag_list = response.get("TagInfoForResource", {}).get("TagList", [])
        return {t["Key"]: t["Value"] for t in tag_list}
    except ClientError as e:
        logger.error("WAFv2 list_tags_for_resource failed for %s: %s",
                     resource_arn, e)
        return {}
