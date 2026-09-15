"""CloudFront — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_CLOUDFRONT_ALARMS = [
    {
        "metric": "CF5xxErrorRate",
        "namespace": "AWS/CloudFront",
        "metric_name": "5xxErrorRate",
        "dimension_key": "DistributionId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CF4xxErrorRate",
        "namespace": "AWS/CloudFront",
        "metric_name": "4xxErrorRate",
        "dimension_key": "DistributionId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CFRequests",
        "namespace": "AWS/CloudFront",
        "metric_name": "Requests",
        "dimension_key": "DistributionId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CFBytesDownloaded",
        "namespace": "AWS/CloudFront",
        "metric_name": "BytesDownloaded",
        "dimension_key": "DistributionId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
]


SPEC = register(ResourceTypeSpec(
    type="CloudFront", label="CloudFront 배포", collector="cloudfront",
    rgt_filters=("cloudfront:distribution",), rgt_prime=True, global_region="us-east-1",
    lifecycle=(Lifecycle("CreateDistribution", CREATE), Lifecycle("DeleteDistribution", DELETE)),
    alarm_defs=_CLOUDFRONT_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CF5xxErrorRate": ("5xxErrorRate", ">", "%"),
        "CF4xxErrorRate": ("4xxErrorRate", ">", "%"),
        "CFRequests": ("Requests", ">", ""),
        "CFBytesDownloaded": ("BytesDownloaded", ">", "B"),
    },
    defaults={
        "CF5xxErrorRate": 1.0,
        "CF4xxErrorRate": 5.0,
        "CFRequests": 1000000.0,
        "CFBytesDownloaded": 10000000000.0,
    },
))
