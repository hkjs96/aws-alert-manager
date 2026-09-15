"""DocDB — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import ResourceTypeSpec, register


_DOCDB_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/DocDB",
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
        "namespace": "AWS/DocDB",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseConnections",
        "namespace": "AWS/DocDB",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="DocDB", label="DocumentDB", collector="docdb",
    rgt_filters=("rds:db",), rgt_prime=True,
    notes="생명주기 이벤트는 RDS 스펙의 것을 공유한다 — CloudTrail이 rds.amazonaws.com의 ModifyDBInstance/DeleteDBInstance로 내고, remediation이 엔진(docdb)으로 판별한다.",
    alarm_defs=_DOCDB_ALARMS,
))
