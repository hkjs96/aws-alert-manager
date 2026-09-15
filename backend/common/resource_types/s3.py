"""S3 — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_S3_ALARMS = [
    {
        "metric": "S34xxErrors",
        "namespace": "AWS/S3",
        "metric_name": "4xxErrors",
        "dimension_key": "BucketName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "S35xxErrors",
        "namespace": "AWS/S3",
        "metric_name": "5xxErrors",
        "dimension_key": "BucketName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "S3BucketSizeBytes",
        "namespace": "AWS/S3",
        "metric_name": "BucketSizeBytes",
        "dimension_key": "BucketName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
        "needs_storage_type": True,
        "treat_missing_data": "missing",  # 일간 메트릭, 중간 기간 missing은 정상 → 상태 유지
    },
    {
        "metric": "S3NumberOfObjects",
        "namespace": "AWS/S3",
        "metric_name": "NumberOfObjects",
        "dimension_key": "BucketName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
        "needs_storage_type": True,
        "treat_missing_data": "missing",  # 일간 메트릭, 중간 기간 missing은 정상 → 상태 유지
    },
]


SPEC = register(ResourceTypeSpec(
    type="S3", label="S3 버킷", collector="s3",
    rgt_filters=("s3",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateBucket", CREATE), Lifecycle("DeleteBucket", DELETE)),
    notes="버킷 메트릭은 버킷 리전에서 — 나열 뒤 리전 조회가 필요하다.",
    alarm_defs=_S3_ALARMS,
))
