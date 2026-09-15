"""
S3 수집기 — 글로벌 나열이라 태그 캐시(RGT)로 나열하지 않는다 (docs/specs/resource-type-registry P3)

버킷 목록은 글로벌(list_buckets)이지만 RGT는 리전 API라 버킷이 **버킷의 리전** 캐시에만 나온다 — 실행 리전 캐시로 나열하면 다른 리전
버킷을 놓친다. 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다(태그는 캐시 **히트만** 믿는다, `trust_negative=False`).
TagName = 버킷 이름. 내부 태그 `_storage_type`·`_filter_id`는 알람·메트릭의 StorageType·FilterId 디멘션이 된다.
메트릭은 스펙(`common/resource_types/s3.py`)의 알람 정의에서 만든다 — 요청 지표(4xx/5xx)는 알람과 같은 빌더라 FilterId 디멘션이 붙는다
(옛 수집기는 BucketName만으로 물어 데이터가 없었다; docs/specs/resource-type-registry tasks 3.4). 네임스페이스 AWS/S3.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.s3 import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_s3_client():
    """S3 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("s3")


def _enumerate() -> list[tuple[str, dict]]:
    """list_buckets 후 버킷마다 get_bucket_tagging(캐시 히트 우선). Monitoring=on만 내부 태그를 붙여 (bucket_name, tags)."""
    client = _get_s3_client()
    try:
        response = client.list_buckets()
    except ClientError as e:
        logger.error("S3 list_buckets failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for bucket in response.get("Buckets", []):
        bucket_name = bucket.get("Name", "")
        tags = dict(_get_bucket_tags(client, bucket_name))
        if tags.get("Monitoring", "").lower() != "on":
            continue
        tags["_storage_type"] = "StandardStorage"
        tags["_filter_id"] = "EntireBucket"
        found.append((bucket_name, tags))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """S3 버킷 존재 여부 확인 — head_bucket."""
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


def _get_bucket_tags(s3_client, bucket_name: str) -> dict:
    """S3 get_bucket_tagging 래퍼. NoSuchTagConfiguration 시 빈 dict 반환."""
    cached = cached_tags(f"arn:aws:s3:::{bucket_name}", trust_negative=False)
    if cached is not None:
        return cached
    try:
        response = s3_client.get_bucket_tagging(Bucket=bucket_name)
        return {t["Key"]: t["Value"] for t in response.get("TagSet", [])}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchTagSet", "NoSuchTagConfiguration"):
            return {}
        logger.error("S3 get_bucket_tagging failed for %s: %s", bucket_name, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
