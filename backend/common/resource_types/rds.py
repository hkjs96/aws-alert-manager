"""RDS — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, MODIFY, TAG_CHANGE, Lifecycle, ResourceTypeSpec, register


_RDS_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/RDS",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeableMemory",
        "namespace": "AWS/RDS",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,  # GB → bytes
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeStorageSpace",
        "namespace": "AWS/RDS",
        "metric_name": "FreeStorageSpace",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseConnections",
        "namespace": "AWS/RDS",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "ReadLatency",
        "namespace": "AWS/RDS",
        "metric_name": "ReadLatency",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 쿼리 없으면 데이터 없음
    },
    {
        "metric": "WriteLatency",
        "namespace": "AWS/RDS",
        "metric_name": "WriteLatency",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 쿼리 없으면 데이터 없음
    },
    {
        "metric": "ConnectionAttempts",
        "namespace": "AWS/RDS",
        "metric_name": "ConnectionAttempts",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 연결 시도 없으면 데이터 없음
    },
]


SPEC = register(ResourceTypeSpec(
    type="RDS", label="RDS 인스턴스", collector="rds",
    rgt_filters=("rds:db",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyDBInstance", MODIFY), Lifecycle("DeleteDBInstance", DELETE),
               Lifecycle("CreateDBInstance", CREATE),
               Lifecycle("AddTagsToResource", TAG_CHANGE), Lifecycle("RemoveTagsFromResource", TAG_CHANGE)),
    notes="rds:db 필터와 이 이벤트들은 Aurora·DocDB 인스턴스도 낸다 — 엔진은 describe로 판별(remediation 엔진 스니핑).",
    alarm_defs=_RDS_ALARMS,
))
