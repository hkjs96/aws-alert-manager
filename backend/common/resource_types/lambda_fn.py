"""Lambda — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, arn_tail, register


_LAMBDA_ALARMS = [
    {
        "metric": "Duration",
        "namespace": "AWS/Lambda",
        "metric_name": "Duration",
        "dimension_key": "FunctionName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Errors",
        "namespace": "AWS/Lambda",
        "metric_name": "Errors",
        "dimension_key": "FunctionName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="Lambda", label="Lambda 함수", collector="lambda_fn",
    rgt_filters=("lambda:function",), rgt_prime=True, identity=arn_tail(":"),
    lifecycle=(Lifecycle("CreateFunction20150331", CREATE), Lifecycle("DeleteFunction20150331", DELETE)),
    alarm_defs=_LAMBDA_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "Duration": ("Duration", ">", "ms"),
        "Errors": ("Errors", ">", ""),
    },
    defaults={
        "Duration": 2500.0,
        "Errors": 0.0,
    },
))
