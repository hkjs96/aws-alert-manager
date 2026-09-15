"""SageMaker — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_SAGEMAKER_ALARMS = [
    {
        "metric": "SMInvocations",
        "namespace": "AWS/SageMaker",
        "metric_name": "Invocations",
        "dimension_key": "EndpointName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMInvocationErrors",
        "namespace": "AWS/SageMaker",
        "metric_name": "InvocationErrors",
        "dimension_key": "EndpointName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMModelLatency",
        "namespace": "AWS/SageMaker",
        "metric_name": "ModelLatency",
        "dimension_key": "EndpointName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMCPU",
        "namespace": "AWS/SageMaker",
        "metric_name": "CPUUtilization",
        "dimension_key": "EndpointName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="SageMaker", label="SageMaker 엔드포인트", collector="sagemaker",
    rgt_filters=("sagemaker:endpoint",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateEndpoint", CREATE), Lifecycle("DeleteEndpoint", DELETE)),
    alarm_defs=_SAGEMAKER_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "SMInvocations": ("Invocations", ">", ""),
        "SMInvocationErrors": ("InvocationErrors", ">", ""),
        "SMModelLatency": ("ModelLatency", ">", "μs"),
        "SMCPU": ("CPUUtilization", ">", "%"),
    },
    defaults={
        "SMInvocations": 100000.0,
        "SMInvocationErrors": 0.0,
        "SMModelLatency": 1000.0,
        "SMCPU": 80.0,
    },
))
