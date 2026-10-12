"""
ACM 수집기 — 다른 타입과 같이 **Monitoring=on 태그가 붙은** 인증서만 감시한다.

2026-03(Req 4.3·13.1)부터 2026-10까지는 태그 없이 ISSUED 인증서 전체를 모았다(Full_Collection) — 우리 계정 하나를 보던
시절엔 편했지만, 첫 실고객 계정에서 고객이 켜지 않은 인증서 2개에 만료 알람이 생겼다. 태그 계약("태그=의도",
docs/specs/monitoring-tag-contract)과도 어긋났다. 지금은:

- 태그 캐시(RGT)가 살아 있으면 Monitoring=on 인증서만 받아 `_identities`가 describe로 도메인·만료를 확인한다.
- 캐시가 없으면 `_enumerate`가 전체를 나열하되 태그를 RGT로 읽어(`tag_resolver._get_acm_tags`) 걸러진다.

TagName은 도메인명(Name 태그로 넣는다 — `_alive`가 도메인으로 역매핑). 메트릭은 스펙(`common/resource_types/acm.py`)의
알람 정의에서 만든다. 네임스페이스 AWS/CertificateManager, 디멘션 CertificateArn.
"""

import functools
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.acm import SPEC
from common.tag_resolver import get_resource_tags_or_none

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_acm_client():
    """ACM 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("acm")


def _live_domain(client, cert_arn: str) -> str | None:
    """ISSUED·미만료 인증서면 도메인(없으면 ""), 아니면 None. describe 실패도 None."""
    try:
        detail = client.describe_certificate(CertificateArn=cert_arn).get("Certificate", {})
    except ClientError as e:
        logger.error("ACM describe_certificate failed for %s: %s", cert_arn, e)
        return None
    if detail.get("Status", "ISSUED") != "ISSUED":
        return None
    not_after = detail.get("NotAfter")
    if not_after and not_after < datetime.now(timezone.utc):
        logger.info("Skipping expired ACM cert %s (expired: %s)", cert_arn, not_after)
        return None
    return _domain_from_cert(detail)


def _with_domain(tags: dict, domain: str) -> dict:
    return {**tags, "Name": domain} if domain else dict(tags)


def _identities(cert_arn: str, tags: dict) -> list[tuple[str, dict]]:
    """태그 캐시 경로 — Monitoring=on 인증서 하나 → [(cert_arn, 태그+Name=도메인)], 발급 안 됐거나 만료면 []."""
    domain = _live_domain(_get_acm_client(), cert_arn)
    return [] if domain is None else [(cert_arn, _with_domain(tags, domain))]


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때 — ISSUED·미만료 인증서 전체 (cert_arn, 실제 태그+Name=도메인). Monitoring 필터는 GenericCollector가 한다.

    태그를 못 읽으면 감시하지 않는다(켜졌다고 가정하지 않는다).
    """
    try:
        client = _get_acm_client()
        pages = client.get_paginator("list_certificates").paginate(CertificateStatuses=["ISSUED"])
    except ClientError as e:
        logger.error("ACM list_certificates failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for cert in page.get("CertificateSummaryList", []):
            cert_arn = cert["CertificateArn"]
            domain = _live_domain(client, cert_arn)
            if domain is None:
                continue
            tags = get_resource_tags_or_none(cert_arn, "ACM")
            if tags is None:
                logger.warning("ACM tags unreadable for %s; not monitoring it", cert_arn)
                tags = {}
            found.append((cert_arn, _with_domain(tags, domain)))
    return found


def _domain_from_cert(cert_detail: dict) -> str:
    """인증서 상세에서 도메인 이름 추출."""
    return cert_detail.get("DomainName", "")


def _alive(tag_names: set[str]) -> set[str]:
    """알람 TagName 집합에서 실제 AWS ACM 인증서가 존재하는 TagName 부분집합 반환.

    TagName은 도메인 이름 형식 (예: 'e2e-test.internal').
    ISSUED 상태의 인증서를 조회하고, 만료되지 않은 인증서의 도메인 이름을
    수집하여 입력 tag_names와의 교집합을 반환한다.
    """
    if not tag_names:
        return set()

    client = _get_acm_client()
    now = datetime.now(timezone.utc)
    alive_domains: set[str] = set()

    try:
        paginator = client.get_paginator("list_certificates")
        for page in paginator.paginate(CertificateStatuses=["ISSUED"]):
            for cert in page.get("CertificateSummaryList", []):
                cert_arn = cert["CertificateArn"]
                try:
                    detail = client.describe_certificate(CertificateArn=cert_arn)
                except ClientError as e:
                    logger.error("ACM describe_certificate failed for %s: %s", cert_arn, e)
                    continue

                cert_detail = detail.get("Certificate", {})
                not_after = cert_detail.get("NotAfter")

                if not_after and not_after < now:
                    continue

                domain = _domain_from_cert(cert_detail)
                if domain:
                    alive_domains.add(domain)
    except ClientError as e:
        logger.error("ACM list_certificates failed: %s", e)
        return set()

    return tag_names & alive_domains


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, identities=_identities)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
