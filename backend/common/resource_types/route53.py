"""Route53 — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_ROUTE53_ALARMS = [
    {
        "metric": "HealthCheckStatus",
        "namespace": "AWS/Route53",
        "metric_name": "HealthCheckStatus",
        "dimension_key": "HealthCheckId",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="Route53", label="Route 53 상태 검사", collector="route53",
    rgt_filters=("route53:healthcheck",), rgt_prime=True, global_region="us-east-1",
    lifecycle=(Lifecycle("CreateHealthCheck", CREATE), Lifecycle("DeleteHealthCheck", DELETE)),
    alarm_defs=_ROUTE53_ALARMS,
))
