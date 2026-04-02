"""
LambdaCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 Lambda 함수 수집 및 CloudWatch 메트릭 조회.
파일명 lambda_fn.py: Python 예약어 lambda 충돌 회피.
네임스페이스: AWS/Lambda, 디멘션: FunctionName.
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
def _get_lambda_client():
    """Lambda 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("lambda")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 Lambda 함수 목록 반환.

    list_functions() paginator로 전체 함수 조회 후
    list_tags()로 태그 확인, Monitoring=on 필터링.
    """
    try:
        client = _get_lambda_client()
        paginator = client.get_paginator("list_functions")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("Lambda list_functions failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for fn in page.get("Functions", []):
            fn_name = fn["FunctionName"]
            fn_arn = fn.get("FunctionArn", "")

            tags = _get_tags(client, fn_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=fn_name,
                    type="Lambda",
                    tags=tags,
                    region=region,
                )
            )

    return resources


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 Lambda 함수 메트릭 조회.

    수집 메트릭 (네임스페이스: AWS/Lambda):
    - Duration (Average) → 'Duration'
    - Errors (Sum) → 'Errors'

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    dim = [{"Name": "FunctionName", "Value": resource_id}]
    metrics: dict[str, float] = {}

    _collect_metric("AWS/Lambda", "Duration", dim,
                    start_time, end_time, "Duration", metrics, CW_STAT_AVG)
    _collect_metric("AWS/Lambda", "Errors", dim,
                    start_time, end_time, "Errors", metrics, CW_STAT_SUM)

    return metrics if metrics else None


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """Lambda 함수 존재 여부 확인."""
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


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for Lambda %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_tags(lambda_client, function_arn: str) -> dict:
    """Lambda list_tags 래퍼. ClientError 시 빈 dict 반환 + error 로그."""
    if not function_arn:
        return {}
    try:
        response = lambda_client.list_tags(Resource=function_arn)
        return response.get("Tags", {})
    except ClientError as e:
        logger.error("Lambda list_tags failed for %s: %s", function_arn, e)
        return {}
