"""WAF — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_WAF_ALARMS = [
    {
        "metric": "WAFBlockedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "BlockedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WAFAllowedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "AllowedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WAFCountedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "CountedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="WAF", label="WAFv2 Web ACL", collector="waf",
    rgt_filters=("wafv2:webacl",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateWebACL", CREATE), Lifecycle("DeleteWebACL", DELETE)),
    notes="REGIONAL 스코프는 리전, CLOUDFRONT 스코프는 us-east-1에서 조회.",
    alarm_defs=_WAF_ALARMS,
))
