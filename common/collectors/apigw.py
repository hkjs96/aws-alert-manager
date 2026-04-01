"""
APIGWCollector - Remaining Resource Monitoring

Monitoring=on 태그가 있는 API Gateway (REST/HTTP/WebSocket) 수집 및 CloudWatch 메트릭 조회.
단일 모듈에서 3가지 API 타입을 수집 (ELB Collector의 ALB/NLB 패턴 준용).
네임스페이스: AWS/ApiGateway, 디멘션: ApiName (REST) 또는 ApiId (HTTP/WS).
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
def _get_apigw_client():
    """API Gateway v1 (REST) 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("apigateway")


@functools.lru_cache(maxsize=None)
def _get_apigwv2_client():
    """API Gateway v2 (HTTP/WS) 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("apigatewayv2")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 API Gateway (REST/HTTP/WebSocket) 목록 반환.

    REST: apigateway 클라이언트 get_rest_apis() + get_tags()
    HTTP/WS: apigatewayv2 클라이언트 get_apis() + Tags 필드
    _api_type Internal_Tag로 REST/HTTP/WEBSOCKET 분기.
    한쪽 API 실패 시 다른 쪽은 계속 수집.
    """
    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    # REST API 수집
    _collect_rest_apis(resources, region)

    # HTTP/WebSocket API 수집
    _collect_v2_apis(resources, region)

    return resources


def _collect_rest_apis(resources: list[ResourceInfo], region: str) -> None:
    """REST API (v1) 수집. 실패 시 로그 후 skip."""
    try:
        client = _get_apigw_client()
        paginator = client.get_paginator("get_rest_apis")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("APIGW get_rest_apis failed: %s", e)
        return

    for page in pages:
        for api in page.get("items", []):
            api_id = api["id"]
            api_name = api.get("name", api_id)

            tags = _get_rest_api_tags(client, api_id, region)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            tags["_api_type"] = "REST"

            resources.append(
                ResourceInfo(
                    id=api_name,
                    type="APIGW",
                    tags=tags,
                    region=region,
                )
            )


def _collect_v2_apis(resources: list[ResourceInfo], region: str) -> None:
    """HTTP/WebSocket API (v2) 수집. 실패 시 로그 후 skip."""
    try:
        client = _get_apigwv2_client()
        paginator = client.get_paginator("get_apis")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("APIGW v2 get_apis failed: %s", e)
        return

    for page in pages:
        for api in page.get("Items", []):
            api_id = api["ApiId"]
            protocol = api.get("ProtocolType", "HTTP")

            tags = api.get("Tags", {})
            if tags.get("Monitoring", "").lower() != "on":
                continue

            api_type = "WEBSOCKET" if protocol == "WEBSOCKET" else "HTTP"
            tags["_api_type"] = api_type

            # v2 API Name을 tags에 포함 (알람 이름 label용)
            api_name = api.get("Name", "")
            if api_name:
                tags.setdefault("Name", api_name)

            resources.append(
                ResourceInfo(
                    id=api_id,
                    type="APIGW",
                    tags=tags,
                    region=region,
                )
            )


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """알람 TagName 집합에서 실제 AWS API Gateway가 존재하는 TagName 부분집합 반환.

    composite TagName ('{api_name}/{api_id}' 형식, '/'포함):
        마지막 '/' 기준으로 분리하여 api_id를 추출하고 v2 API (HTTP/WS)의
        ApiId와 비교한다.
    non-composite TagName ('/' 미포함):
        REST API 이름으로 간주하고 get_rest_apis 결과의 name과 비교한다.
    """
    if not tag_names:
        return set()

    composite: dict[str, str] = {}   # api_id -> original tag_name
    rest_names: dict[str, str] = {}  # api_name -> original tag_name

    for tag_name in tag_names:
        if "/" in tag_name:
            api_id = tag_name.rsplit("/", 1)[1]
            composite[api_id] = tag_name
        else:
            rest_names[tag_name] = tag_name

    alive: set[str] = set()

    # v2 APIs (HTTP/WebSocket) — match by ApiId
    if composite:
        try:
            v2 = _get_apigwv2_client()
            paginator = v2.get_paginator("get_apis")
            for page in paginator.paginate():
                for api in page.get("Items", []):
                    api_id = api["ApiId"]
                    if api_id in composite:
                        alive.add(composite[api_id])
        except ClientError as e:
            logger.error("APIGW v2 get_apis failed: %s", e)

    # REST APIs — match by name
    if rest_names:
        try:
            client = _get_apigw_client()
            paginator = client.get_paginator("get_rest_apis")
            for page in paginator.paginate():
                for api in page.get("items", []):
                    name = api.get("name", "")
                    if name in rest_names:
                        alive.add(rest_names[name])
        except ClientError as e:
            logger.error("APIGW get_rest_apis failed: %s", e)

    return alive


def get_metrics(
    resource_id: str, resource_tags: dict | None = None,
) -> dict[str, float] | None:
    """
    CloudWatch에서 API Gateway 메트릭 조회.

    _api_type에 따라 디멘션 키와 메트릭 이름 분기:
    - REST: ApiName, Latency/4XXError/5XXError
    - HTTP: ApiId, Latency/4xx/5xx
    - WEBSOCKET: ApiId, ConnectCount/MessageCount/IntegrationError/ExecutionError

    데이터 없으면 해당 메트릭 skip. 모두 없으면 None 반환.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    api_type = resource_tags.get("_api_type", "REST")
    metrics: dict[str, float] = {}

    if api_type == "REST":
        _collect_rest_metrics(resource_id, start_time, end_time, metrics)
    elif api_type == "HTTP":
        _collect_http_metrics(resource_id, start_time, end_time, metrics)
    elif api_type == "WEBSOCKET":
        _collect_ws_metrics(resource_id, start_time, end_time, metrics)

    return metrics if metrics else None


def _collect_rest_metrics(api_name, start_time, end_time, metrics):
    """REST API 메트릭 조회. 디멘션: ApiName."""
    dim = [{"Name": "ApiName", "Value": api_name}]
    _collect_metric("AWS/ApiGateway", "Latency", dim,
                    start_time, end_time, "ApiLatency", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ApiGateway", "4XXError", dim,
                    start_time, end_time, "Api4XXError", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ApiGateway", "5XXError", dim,
                    start_time, end_time, "Api5XXError", metrics, CW_STAT_SUM)


def _collect_http_metrics(api_id, start_time, end_time, metrics):
    """HTTP API 메트릭 조회. 디멘션: ApiId."""
    dim = [{"Name": "ApiId", "Value": api_id}]
    _collect_metric("AWS/ApiGateway", "Latency", dim,
                    start_time, end_time, "ApiLatency", metrics, CW_STAT_AVG)
    _collect_metric("AWS/ApiGateway", "4xx", dim,
                    start_time, end_time, "Api4xx", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ApiGateway", "5xx", dim,
                    start_time, end_time, "Api5xx", metrics, CW_STAT_SUM)


def _collect_ws_metrics(api_id, start_time, end_time, metrics):
    """WebSocket API 메트릭 조회. 디멘션: ApiId."""
    dim = [{"Name": "ApiId", "Value": api_id}]
    _collect_metric("AWS/ApiGateway", "ConnectCount", dim,
                    start_time, end_time, "WsConnectCount", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ApiGateway", "MessageCount", dim,
                    start_time, end_time, "WsMessageCount", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ApiGateway", "IntegrationError", dim,
                    start_time, end_time, "WsIntegrationError", metrics, CW_STAT_SUM)
    _collect_metric("AWS/ApiGateway", "ExecutionError", dim,
                    start_time, end_time, "WsExecutionError", metrics, CW_STAT_SUM)


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip + info 로그."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for APIGW %s: no data", result_key,
                    dimensions[0]["Value"] if dimensions else "unknown")


def _get_rest_api_tags(apigw_client, api_id: str, region: str) -> dict:
    """REST API 태그 조회. get_tags() 사용. ClientError 시 빈 dict 반환."""
    try:
        # REST API ARN: arn:aws:apigateway:{region}::/restapis/{api_id}
        arn = f"arn:aws:apigateway:{region}::/restapis/{api_id}"
        response = apigw_client.get_tags(resourceArn=arn)
        return response.get("tags", {})
    except ClientError as e:
        logger.error("APIGW get_tags failed for %s: %s", api_id, e)
        return {}
