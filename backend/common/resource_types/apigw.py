"""APIGW — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_APIGW_REST_ALARMS = [
    {
        "metric": "ApiLatency",
        "namespace": "AWS/ApiGateway",
        "metric_name": "Latency",
        "dimension_key": "ApiName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api4XXError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "4XXError",
        "dimension_key": "ApiName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api5XXError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "5XXError",
        "dimension_key": "ApiName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


_APIGW_HTTP_ALARMS = [
    {
        "metric": "ApiLatency",
        "namespace": "AWS/ApiGateway",
        "metric_name": "Latency",
        "dimension_key": "ApiId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api4xx",
        "namespace": "AWS/ApiGateway",
        "metric_name": "4xx",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api5xx",
        "namespace": "AWS/ApiGateway",
        "metric_name": "5xx",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


_APIGW_WEBSOCKET_ALARMS = [
    {
        "metric": "WsConnectCount",
        "namespace": "AWS/ApiGateway",
        "metric_name": "ConnectCount",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsMessageCount",
        "namespace": "AWS/ApiGateway",
        "metric_name": "MessageCount",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsIntegrationError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "IntegrationError",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsExecutionError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "ExecutionError",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


def _get_apigw_alarm_defs(resource_tags: dict) -> list[dict]:
    """APIGW _api_type별 알람 정의 동적 빌드 (Aurora 패턴 준용)."""
    api_type = resource_tags.get("_api_type", "REST")
    if api_type == "HTTP":
        return _APIGW_HTTP_ALARMS
    if api_type == "WEBSOCKET":
        return _APIGW_WEBSOCKET_ALARMS
    return _APIGW_REST_ALARMS


SPEC = register(ResourceTypeSpec(
    type="APIGW", label="API Gateway", collector="apigw",
    rgt_filters=("apigateway:restapis", "apigateway:apis"), rgt_prime=True,
    lifecycle=(Lifecycle("CreateRestApi", CREATE), Lifecycle("CreateApi", CREATE),
               Lifecycle("DeleteRestApi", DELETE), Lifecycle("DeleteApi", DELETE)),
    notes="REST(restapis, 디멘션 ApiName)와 HTTP/WebSocket(apis, 디멘션 ApiId)은 다른 리소스 타입 — 필터 둘, 알람 정의는 _api_type 태그로 갈린다.",
    alarm_defs=_get_apigw_alarm_defs,
    variants=tuple({"_api_type": t} for t in ("REST", "HTTP", "WEBSOCKET")),
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "ApiLatency": ("Latency", ">", "ms"),
        "Api4XXError": ("4XXError", ">", ""),
        "Api5XXError": ("5XXError", ">", ""),
        "Api4xx": ("4xx", ">", ""),
        "Api5xx": ("5xx", ">", ""),
        "WsConnectCount": ("ConnectCount", ">", ""),
        "WsMessageCount": ("MessageCount", ">", ""),
        "WsIntegrationError": ("IntegrationError", ">", ""),
        "WsExecutionError": ("ExecutionError", ">", ""),
    },
    defaults={
        "ApiLatency": 3000.0,
        "Api4XXError": 1.0,
        "Api5XXError": 1.0,
        "Api4xx": 1.0,
        "Api5xx": 1.0,
        "WsConnectCount": 1000.0,
        "WsMessageCount": 10000.0,
        "WsIntegrationError": 0.0,
        "WsExecutionError": 0.0,
    },
))
