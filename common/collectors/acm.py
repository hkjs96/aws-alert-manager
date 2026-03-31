"""
ACMCollector - Remaining Resource Monitoring

ACM 인증서 만료 모니터링. Full_Collection: 태그 필터 없이 ISSUED 인증서 전체 수집.
Monitoring=on 태그를 자동 삽입하여 하위 파이프라인 호환성 유지.
네임스페이스: AWS/CertificateManager, 디멘션: CertificateArn.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES

logger = logging.getLogger(__name__)

CW_STAT_MIN = "Minimum"


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_acm_client():
    """ACM 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("acm")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    계정 내 모든 ISSUED ACM 인증서 수집 (Full_Collection).

    만료된 인증서는 제외. 도메인 이름을 Name 태그로 설정하여
    알람 이름에 도메인이 표시되도록 한다.
    """
    try:
        client = _get_acm_client()
        paginator = client.get_paginator("list_certificates")
        pages = paginator.paginate(CertificateStatuses=["ISSUED"])
    except ClientError as e:
        logger.error("ACM list_certificates failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"
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

            resources.append(
                ResourceInfo(
                    id=cert_arn,
                    type="ACM",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def _domain_from_cert(cert_detail: dict) -> str:
    """인증서 상세에서 도메인 이름 추출."""
    return cert_detail.get("DomainName", "")


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 ACM 인증서 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/CertificateManager):
    - DaysToExpiry (Minimum) → 'DaysToExpiry'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "CertificateArn", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/CertificateManager", "DaysToExpiry", dim,
                    start_time, end_time, "DaysToExpiry", metrics)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_MIN)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for ACM %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")
