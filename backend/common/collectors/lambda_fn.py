"""
Lambda 수집기 — 나열은 범용(태그 캐시), 여기엔 describe 폴백과 존재 확인만 (docs/specs/resource-type-registry P3)

파일명 lambda_fn.py: Python 예약어 lambda 충돌 회피. TagName = 함수 이름(ARN의 마지막 조각, 스펙 `identity`).
메트릭은 스펙(`common/resource_types/lambda_fn.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/Lambda, 디멘션 FunctionName.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector
from common.resource_types.lambda_fn import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_lambda_client():
    """Lambda 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("lambda")


def _enumerate() -> list[tuple[str, dict]]:
    """태그 캐시가 없을 때: list_functions 후 함수마다 list_tags(N+1). (function_name, tags)."""
    try:
        client = _get_lambda_client()
        paginator = client.get_paginator("list_functions")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Lambda list_functions failed: %s", e)
        raise

    found: list[tuple[str, dict]] = []
    for page in pages:
        for fn in page.get("Functions", []):
            found.append((fn["FunctionName"], _get_tags(client, fn.get("FunctionArn", ""))))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """Lambda 함수 존재 여부 확인 — get_function."""
    client = _get_lambda_client()
    alive: set[str] = set()
    for name in tag_names:
        try:
            client.get_function(FunctionName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("Lambda function not found (orphan): %s", name)
            else:
                logger.error("get_function failed for %s: %s", name, e)
    return alive


def _get_tags(lambda_client, function_arn: str) -> dict:
    """Lambda list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    cached = cached_tags(function_arn)
    if cached is not None:
        return cached
    if not function_arn:
        return {}
    try:
        response = lambda_client.list_tags(Resource=function_arn)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("Lambda list_tags failed for %s: %s", function_arn, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
