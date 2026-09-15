"""ECS — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_ECS_ALARMS = [
    {
        "metric": "EcsCPU",
        "namespace": "AWS/ECS",
        "metric_name": "CPUUtilization",
        "dimension_key": "ServiceName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "EcsMemory",
        "namespace": "AWS/ECS",
        "metric_name": "MemoryUtilization",
        "dimension_key": "ServiceName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="ECS", label="ECS 서비스", collector="ecs",
    rgt_filters=("ecs:service",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateService", CREATE), Lifecycle("DeleteService", DELETE)),
    notes=("identity 없음: 구 형식 서비스 ARN엔 클러스터 이름이 없고 launchType·클러스터명(_cluster_name, ClusterName 디멘션)에 "
           "describe_services가 필요하다 — RGT 나열로 아낄 콜이 없어 수집기의 describe 나열만 쓴다."),
    alarm_defs=_ECS_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "EcsCPU": ("CPUUtilization", ">", "%"),
        "EcsMemory": ("MemoryUtilization", ">", "%"),
    },
    defaults={
        "EcsCPU": 80.0,
        "EcsMemory": 80.0,
    },
))
