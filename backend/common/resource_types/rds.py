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
    notes=("rds:db 필터와 이 이벤트들은 Aurora·DocDB 인스턴스도 낸다 — 엔진은 describe로 판별(remediation 엔진 스니핑). "
           "identity 없음: 같은 이유로 나열도 describe(rds 수집기가 RDS·AuroraRDS 둘을 낸다). 메트릭은 수집기 오버라이드 — "
           "bytes→GB 변환과 개명 전 결과 키(FreeMemoryGB·FreeStorageGB)가 daily_monitor의 방향 판정에 묶여 있다."),
    alarm_defs=_RDS_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CPUUtilization": ("CPUUtilization", ">", "%"),
        "FreeableMemory": ("FreeableMemory", "<", "GB"),
        "FreeStorageSpace": ("FreeStorageSpace", "<", "GB"),
        "DatabaseConnections": ("DatabaseConnections", ">", ""),
        "ReadLatency": ("ReadLatency", ">", "s"),
        "WriteLatency": ("WriteLatency", ">", "s"),
        "ConnectionAttempts": ("ConnectionAttempts", ">", ""),
    },
    defaults={
        "CPUUtilization": 80.0,
        "FreeableMemory": 2.0,
        "FreeStorageSpace": 10.0,
        "DatabaseConnections": 100.0,
        "ReadLatency": 0.02,
        "WriteLatency": 0.02,
        "ConnectionAttempts": 500.0,
    },
))
