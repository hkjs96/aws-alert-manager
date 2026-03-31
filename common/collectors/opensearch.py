"""
OpenSearchCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 OpenSearch 도메인 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/ES, Compound Dimension: DomainName + ClientId.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import (
    query_metric,
    CW_LOOKBACK_MINUTES,
    CW_STAT_AVG,
)

logger = logging.getLogger(__name__)

CW_STAT_MAX = "Maximum"
CW_STAT_MIN = "Minimum"


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

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


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 OpenSearch 도메인 목록 반환.

    list_domain_names() → describe_domains() → list_tags()로 태그 확인.
    _client_id Internal_Tag로 AWS 계정 ID를 저장 (Compound Dimension용).
    """
    try:
        client = _get_opensearch_client()
        domain_names_resp = client.list_domain_names()
    except ClientError as e:
        logger.error("OpenSearch list_domain_names failed: %s", e)
        raise

    domain_names = [
        d["DomainName"] for d in domain_names_resp.get("DomainNames", [])
    ]
    if not domain_names:
        return []

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"
    account_id = _get_account_id()

    # describe_domains는 최대 5개씩 배치 호출
    for i in range(0, len(domain_names), 5):
        batch = domain_names[i:i + 5]
        try:
            resp = client.describe_domains(DomainNames=batch)
        except ClientError as e:
            logger.error("OpenSearch describe_domains failed: %s", e)
            continue

        for domain in resp.get("DomainStatusList", []):
            domain_name = domain["DomainName"]
            domain_arn = domain.get("ARN", "")

            tags = _get_tags(client, domain_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            # _client_id Internal_Tag: Compound Dimension용 계정 ID
            client_id = account_id
            if not client_id and domain_arn:
                # ARN에서 account_id 파싱 폴백
                # arn:aws:es:region:account-id:domain/name
                arn_parts = domain_arn.split(":")
                if len(arn_parts) >= 5:
                    client_id = arn_parts[4]

            tags["_client_id"] = client_id

            resources.append(
                ResourceInfo(
                    id=domain_name,
                    type="OpenSearch",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 OpenSearch 도메인 메트릭 조회.

    Compound Dimension: DomainName + ClientId.
    ClientId는 resource_tags["_client_id"]에서 조회.

    수집 메트릭 (네임스페이스: AWS/ES):
    - ClusterStatus.red (Maximum) → 'ClusterStatusRed'
    - ClusterStatus.yellow (Maximum) → 'ClusterStatusYellow'
    - FreeStorageSpace (Minimum) → 'OSFreeStorageSpace'
    - ClusterIndexWritesBlocked (Maximum) → 'ClusterIndexWritesBlocked'
    - CPUUtilization (Average) → 'OsCPU'
    - JVMMemoryPressure (Maximum) → 'JVMMemoryPressure'
    - MasterCPUUtilization (Average) → 'MasterCPU'
    - MasterJVMMemoryPressure (Maximum) → 'MasterJVMMemoryPressure'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    # Compound Dimension: DomainName + ClientId
    dim = [{"Name": "DomainName", "Value": resource_id}]
    client_id = resource_tags.get("_client_id", "")
    if client_id:
        dim.append({"Name": "ClientId", "Value": client_id})

    metrics: dict[str, float] = {}

    _collect_metric("AWS/ES", "ClusterStatus.red", dim,
                    start_time, end_time, "ClusterStatusRed", metrics, CW_STAT_MAX)
    _collect_metric("AWS/ES", "ClusterStatus.yellow", dim,
                    start_time, end_time, "ClusterStatusYellow", metrics, CW_STAT_MAX)
    _collect_metric("AWS/ES", "FreeStorageSpace", dim,
                    start_time, end_time, "OSFreeStorageSpace", metrics, CW_STAT_MIN)
    _collect_metric("AWS/ES", "ClusterIndexWritesBlocked", dim,
                    start_time, end_time, "ClusterIndexWritesBlocked", metrics, CW_STAT_MAX)
    _collect_metric("AWS/ES", "CPUUtilization", dim,
                    start_time, end_time, "OsCPU", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ES", "JVMMemoryPressure", dim,
                    start_time, end_time, "JVMMemoryPressure", metrics, CW_STAT_MAX)
    _collect_metric("AWS/ES", "MasterCPUUtilization", dim,
                    start_time, end_time, "MasterCPU", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ES", "MasterJVMMemoryPressure", dim,
                    start_time, end_time, "MasterJVMMemoryPressure", metrics, CW_STAT_MAX)

    return metrics if metrics else None


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for OpenSearch %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(opensearch_client, domain_arn: str) -> dict:
    """OpenSearch list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not domain_arn:
        return {}
    try:
        response = opensearch_client.list_tags(ARN=domain_arn)
        return {t["Key"]: t["Value"] for t in response.get("TagList", [])}
    except ClientError as e:
        logger.error("OpenSearch list_tags failed for %s: %s", domain_arn, e)
        return {}
