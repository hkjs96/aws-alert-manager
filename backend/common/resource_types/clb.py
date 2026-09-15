"""CLB — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import ResourceTypeSpec, register


_CLB_ALARMS = [
    {
        "metric": "CLBUnHealthyHost",
        "namespace": "AWS/ELB",
        "metric_name": "UnHealthyHostCount",
        "dimension_key": "LoadBalancerName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLB5XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_ELB_5XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLB4XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_ELB_4XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLBBackend5XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_Backend_5XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLBBackend4XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_Backend_4XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "SurgeQueueLength",
        "namespace": "AWS/ELB",
        "metric_name": "SurgeQueueLength",
        "dimension_key": "LoadBalancerName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "SpilloverCount",
        "namespace": "AWS/ELB",
        "metric_name": "SpilloverCount",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="CLB", label="Classic Load Balancer", collector="clb",
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    notes=("생명주기 이벤트는 ALB 스펙(target=ELB)에. ARN에 loadbalancer/app|net 접미가 없는 것이 classic — 태그 캐시 나열은 "
           "수집기 모듈의 _identities가 그 판별을 맡는다(필터가 ALB/NLB와 공유)."),
    alarm_defs=_CLB_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CLBUnHealthyHost": ("UnHealthyHostCount", ">", ""),
        "CLB5XX": ("HTTPCode_ELB_5XX", ">", ""),
        "CLB4XX": ("HTTPCode_ELB_4XX", ">", ""),
        "CLBBackend5XX": ("HTTPCode_Backend_5XX", ">", ""),
        "CLBBackend4XX": ("HTTPCode_Backend_4XX", ">", ""),
        "SurgeQueueLength": ("SurgeQueueLength", ">", ""),
        "SpilloverCount": ("SpilloverCount", ">", ""),
    },
    defaults={
        "CLBUnHealthyHost": 0.0,
        "CLB5XX": 300.0,
        "CLB4XX": 300.0,
        "CLBBackend5XX": 300.0,
        "CLBBackend4XX": 300.0,
        "SurgeQueueLength": 300.0,
        "SpilloverCount": 300.0,
    },
))
