"""
S3Collector - Extended Resource Monitoring (Compound Dimension)

Monitoring=on 태그가 있는 S3 버킷 수집 및 CloudWatch 메트릭 조회.
네임스페이스: AWS/S3, Compound_Dimension: BucketName + StorageType (일부 메트릭).
S3 get_bucket_tagging은 TagSet 구조 사용, NoSuchTagConfiguration 처리 필요.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_s3_client():
    """S3 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("s3")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 S3 버킷 목록 반환.

    list_buckets() → get_bucket_tagging() → Monitoring=on 필터링.
    NoSuchTagConfiguration 에러 처리 (태그 없는 버킷).
    _storage_type Internal_Tag 기본값 "StandardStorage" 설정.
    """
    client = _get_s3_client()
    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    try:
        response = client.list_buckets()
    except ClientError as e:
        logger.error("S3 list_buckets failed: %s", e)
        raise

    for bucket in response.get("Buckets", []):
        bucket_name = bucket.get("Name", "")
        tags = _get_bucket_tags(client, bucket_name)
        if tags.get("Monitoring", "").lower() != "on":
            continue

        tags["_storage_type"] = "StandardStorage"
        tags["_filter_id"] = "EntireBucket"

        resources.append(
            ResourceInfo(
                id=bucket_name,
                type="S3",
                tags=tags,
                region=region,
            )
        )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 S3 버킷 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/S3):
    - 4xxErrors (Sum) → 'S34xxErrors' (Request_Metrics 필요, 데이터 미반환 시 warning)
    - 5xxErrors (Sum) → 'S35xxErrors' (Request_Metrics 필요, 데이터 미반환 시 warning)
    - BucketSizeBytes (Average) → 'S3BucketSizeBytes' (StorageType compound dim)
    - NumberOfObjects (Average) → 'S3NumberOfObjects' (StorageType compound dim)

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    storage_type = resource_tags.get("_storage_type", "StandardStorage")

    # Simple dimension (4xx/5xx errors - Request Metrics)
    bucket_dim = [{"Name": "BucketName", "Value": resource_id}]
    # Compound dimension (BucketSizeBytes/NumberOfObjects need StorageType)
    storage_dims = [
        {"Name": "BucketName", "Value": resource_id},
        {"Name": "StorageType", "Value": storage_type},
    ]

    metrics: dict[str, float] = {}

    # Request Metrics (may not have data if not configured)
    _collect_request_metric("AWS/S3", "4xxErrors", bucket_dim,
                            start_time, end_time, "S34xxErrors", metrics,
                            CW_STAT_SUM, resource_id)
    _collect_request_metric("AWS/S3", "5xxErrors", bucket_dim,
                            start_time, end_time, "S35xxErrors", metrics,
                            CW_STAT_SUM, resource_id)

    # Storage Metrics (with StorageType compound dimension)
    _collect_metric("AWS/S3", "BucketSizeBytes", storage_dims,
                    start_time, end_time, "S3BucketSizeBytes", metrics,
                    CW_STAT_AVG)
    _collect_metric("AWS/S3", "NumberOfObjects", storage_dims,
                    start_time, end_time, "S3NumberOfObjects", metrics,
                    CW_STAT_AVG)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """S3 버킷 존재 여부 확인."""
    client = _get_s3_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.head_bucket(Bucket=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                logger.info("S3 bucket not found (orphan): %s", name)
            else:
                logger.error("head_bucket failed for %s: %s", name, e)
    return alive


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for S3 %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _collect_request_metric(namespace, cw_metric_name, dimensions,
                            start_time, end_time, result_key, metrics_dict,
                            stat, bucket_name):
    """Request Metrics 조회. 데이터 미반환 시 warning 로그 (Request_Metrics 미설정 가능)."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.warning("S3 %s metric missing for %s: Request_Metrics may not be configured",
                       result_key, bucket_name)


def _get_bucket_tags(s3_client, bucket_name: str) -> dict:
    """S3 get_bucket_tagging 래퍼. NoSuchTagConfiguration 시 빈 dict 반환."""
    try:
        response = s3_client.get_bucket_tagging(Bucket=bucket_name)
        tag_set = response.get("TagSet", [])
        return {t["Key"]: t["Value"] for t in tag_set}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchTagSet", "NoSuchTagConfiguration"):
            return {}
        logger.error("S3 get_bucket_tagging failed for %s: %s",
                     bucket_name, e)
        return {}
