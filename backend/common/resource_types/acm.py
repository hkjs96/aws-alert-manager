"""ACM — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import DELETE, Lifecycle, ResourceTypeSpec, register


_ACM_ALARMS = [
    {
        "metric": "DaysToExpiry",
        "namespace": "AWS/CertificateManager",
        "metric_name": "DaysToExpiry",
        "dimension_key": "CertificateArn",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
        "treat_missing_data": "missing",
    },
]


SPEC = register(ResourceTypeSpec(
    type="ACM", label="ACM 인증서", collector="acm",
    rgt_filters=("acm:certificate",), rgt_prime=True,
    lifecycle=(Lifecycle("DeleteCertificate", DELETE),),
    notes="TagName은 도메인명 — alive 판정이 list_certificates+describe로 역매핑한다.",
    alarm_defs=_ACM_ALARMS,
))
