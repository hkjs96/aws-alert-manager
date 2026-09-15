"""
ACM 수집기 — Full_Collection: 태그 없이 ISSUED 인증서 전체를 모으므로 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

RGT는 태그가 있는 리소스만 돌려주는데 여기는 태그 없는 인증서도 대상이다(Req 13.1) — 스펙에 `identity`가 없고 이 모듈의
`_enumerate`가 유일한 나열이다. Monitoring=on 태그를 자동 삽입하여 하위 파이프라인 호환성 유지. TagName은 도메인명(Name 태그).
메트릭은 스펙(`common/resource_types/acm.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/CertificateManager, 디멘션 CertificateArn.
"""

import functools
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.acm import SPEC

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_acm_client():
    """ACM 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("acm")


def _enumerate() -> list[tuple[str, dict]]:
    """계정 내 모든 ISSUED·미만료 ACM 인증서 (cert_arn, {"Monitoring": "on", "Name": domain}).

    만료된 인증서는 제외. 도메인 이름을 Name 태그로 설정하여 알람 이름에 도메인이 표시되도록 한다.
    """
    try:
        client = _get_acm_client()
        paginator = client.get_paginator("list_certificates")
        pages = paginator.paginate(CertificateStatuses=["ISSUED"])
    except ClientError as e:
        logger.error("ACM list_certificates failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    now = datetime.now(timezone.utc)

    for page in pages:
        for cert in page.get("CertificateSummaryList", []):
            cert_arn = cert["CertificateArn"]
            try:
                detail = client.describe_certificate(CertificateArn=cert_arn)
            except ClientError as e:
                logger.error("ACM describe_certificate failed for %s: %s", cert_arn, e)
                continue

            cert_detail = detail.get("Certificate", {})
            not_after = cert_detail.get("NotAfter")

            # 이미 만료된 인증서 제외
            if not_after and not_after < now:
                logger.info("Skipping expired ACM cert %s (expired: %s)", cert_arn, not_after)
                continue

            domain = _domain_from_cert(cert_detail)
            tags: dict = {"Monitoring": "on"}
            if domain:
                tags["Name"] = domain
            found.append((cert_arn, tags))

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


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
