"""
OpenSearch 수집기 — 나열은 범용(태그 캐시), 여기엔 ClientId 내부 태그·describe 폴백·존재 확인만 (docs/specs/resource-type-registry P3)

CloudWatch 복합 디멘션 DomainName + ClientId(계정 ID). TagName = 도메인 이름(ARN `domain/<name>`). 계정 ID를 `_client_id` 내부 태그로
붙여야 해서 스펙 `identity` 대신 이 모듈의 `_identities`가 맡는다 — 태그 캐시 경로는 ARN의 계정 세그먼트를 쓰고(STS 콜 없음;
RGT가 돌려주는 리소스는 자격증명 계정의 것이라 같다), describe 폴백은 옛 코드대로 STS 우선·ARN 보조다.
메트릭은 스펙(`common/resource_types/opensearch.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/ES.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.opensearch import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_opensearch_client():
    """OpenSearch 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("opensearch")


@functools.lru_cache(maxsize=None)
def _get_sts_client():
    """STS 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("sts")


def _get_account_id() -> str:
    """STS get_caller_identity로 AWS 계정 ID 조회."""
    try:
        return _get_sts_client().get_caller_identity()["Account"]
    except ClientError as e:
        logger.error("STS get_caller_identity failed: %s", e)
        return ""


def _account_from_arn(domain_arn: str) -> str:
    arn_parts = domain_arn.split(":")
    return arn_parts[4] if len(arn_parts) >= 5 else ""


def _identities(arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로: ARN `arn:aws:es:<region>:<account>:domain/<name>` → (도메인 이름, 태그 + _client_id=계정)."""
    domain_tags = dict(tags)
    domain_tags["_client_id"] = _account_from_arn(arn)
    return [(arn.rsplit("/", 1)[-1], domain_tags)]


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_domain_names → describe_domains(5개씩) → 도메인마다 list_tags. (domain_name, tags + _client_id)."""
    try:
        client = _get_opensearch_client()
        domain_names_resp = client.list_domain_names()
    except ClientError as e:
        logger.error("OpenSearch list_domain_names failed: %s", e)
        raise

    domain_names = [d["DomainName"] for d in domain_names_resp.get("DomainNames", [])]
    if not domain_names:
        return []

    found: list[tuple[str, dict]] = []
    account_id = _get_account_id()

    for i in range(0, len(domain_names), 5):
        batch = domain_names[i:i + 5]
        try:
            resp = client.describe_domains(DomainNames=batch)
        except ClientError as e:
            logger.error("OpenSearch describe_domains failed: %s", e)
            continue

        for domain in resp.get("DomainStatusList", []):
            domain_arn = domain.get("ARN", "")
            tags = _get_tags(client, domain_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 캐시 미스 시 도메인마다 태그 API를 이미 불렀다 — 이후 작업만 아낀다
            tags["_client_id"] = account_id or _account_from_arn(domain_arn)
            found.append((domain["DomainName"], tags))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """OpenSearch 도메인 존재 여부 확인 — describe_domains(5개씩), Deleted 제외."""
    client = _get_opensearch_client()
    alive: set[str] = set()
    name_list = list(tag_names)
    for i in range(0, len(name_list), 5):
        batch = name_list[i:i + 5]
        try:
            resp = client.describe_domains(DomainNames=batch)
            for d in resp.get("DomainStatusList", []):
                if not d.get("Deleted", False):
                    alive.add(d["DomainName"])
        except ClientError as e:
            logger.error("describe_domains failed: %s", e)
    return alive


def _get_tags(opensearch_client, domain_arn: str) -> dict:
    """OpenSearch list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    cached = cached_tags(domain_arn)
    if cached is not None:
        return cached
    if not domain_arn:
        return {}
    try:
        response = opensearch_client.list_tags(ARN=domain_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("OpenSearch list_tags failed for %s: %s", domain_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
