"""DynamoDB — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_DYNAMODB_ALARMS = [
    {
        "metric": "DDBReadCapacity",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ConsumedReadCapacityUnits",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "DDBWriteCapacity",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ConsumedWriteCapacityUnits",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "ThrottledRequests",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ThrottledRequests",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "DDBSystemErrors",
        "namespace": "AWS/DynamoDB",
        "metric_name": "SystemErrors",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="DynamoDB", label="DynamoDB 테이블", collector="dynamodb",
    rgt_filters=("dynamodb:table",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateTable", CREATE), Lifecycle("DeleteTable", DELETE)),
    alarm_defs=_DYNAMODB_ALARMS,
))
