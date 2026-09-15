"""AuroraRDS — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import ResourceTypeSpec, register


_AURORA_RDS_ALARMS = [
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
        "transform_threshold": lambda gb: gb * 1073741824,
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
        "metric": "FreeLocalStorage",
        "namespace": "AWS/RDS",
        "metric_name": "FreeLocalStorage",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "ReplicaLag",
        "namespace": "AWS/RDS",
        "metric_name": "AuroraReplicaLagMaximum",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "missing",
    },
]


_AURORA_READER_REPLICA_LAG = {
    "metric": "ReaderReplicaLag",
    "namespace": "AWS/RDS",
    "metric_name": "AuroraReplicaLag",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Maximum",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
    "treat_missing_data": "missing",
}


_AURORA_ACU_UTILIZATION = {
    "metric": "ACUUtilization",
    "namespace": "AWS/RDS",
    "metric_name": "ACUUtilization",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Average",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
    "treat_missing_data": "breaching",  # Serverless v2 실행 중이면 항상 발행
}


_AURORA_SERVERLESS_CAPACITY = {
    "metric": "ServerlessDatabaseCapacity",
    "namespace": "AWS/RDS",
    "metric_name": "ServerlessDatabaseCapacity",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Average",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
}


def _get_aurora_alarm_defs(resource_tags: dict) -> list[dict]:
    """Aurora 인스턴스 변형별 알람 정의 동적 빌드.

    Provisioned: CPU, FreeMemoryGB, Connections, FreeLocalStorageGB + lag
    Serverless v2: CPU, ACUUtilization, Connections + lag
      - FreeMemoryGB 제외: Serverless v2에서 이 메트릭은 "max ACU까지 남은 여유"를 의미하며
        ACUUtilization과 중복됨 (AWS 공식 문서 참조)
      - ServerlessDatabaseCapacity 제외: ACUUtilization이 이미 비율로 커버
    """
    is_serverless = resource_tags.get("_is_serverless_v2") == "true"
    is_writer = resource_tags.get("_is_cluster_writer") == "true"
    has_readers = resource_tags.get("_has_readers") == "true"

    if is_serverless:
        # Serverless v2: CPU + ACUUtilization + Connections (3개)
        alarms = [_AURORA_RDS_ALARMS[0], _AURORA_ACU_UTILIZATION, _AURORA_RDS_ALARMS[2]]
    else:
        # Provisioned: CPU + FreeMemoryGB + Connections + FreeLocalStorageGB
        alarms = list(_AURORA_RDS_ALARMS[:4])

    if is_writer and has_readers:
        alarms.append(_AURORA_RDS_ALARMS[4])  # ReplicaLag
    elif not is_writer:
        alarms.append(_AURORA_READER_REPLICA_LAG)

    return alarms


SPEC = register(ResourceTypeSpec(
    type="AuroraRDS", label="Aurora", collector="rds",
    rgt_filters=("rds:db",), rgt_prime=True,
    notes="RDS 스펙의 이벤트·필터를 공유한다. 알람 정의는 Serverless v2/Writer/Readers 태그로 갈린다.",
    alarm_defs=_get_aurora_alarm_defs,
    variants=tuple(
        {"_is_serverless_v2": s, "_is_cluster_writer": w, "_has_readers": r}
        for s in ("true", "false") for w in ("true", "false") for r in ("true", "false")
    ),
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CPUUtilization": ("CPUUtilization", ">", "%"),
        "ACUUtilization": ("ACUUtilization", ">", "%"),
        "DatabaseConnections": ("DatabaseConnections", ">", ""),
        "ReplicaLag": ("AuroraReplicaLagMaximum", ">", "μs"),
        "ReaderReplicaLag": ("AuroraReplicaLag", ">", "μs"),
        "FreeableMemory": ("FreeableMemory", "<", "GB"),
        "FreeLocalStorage": ("FreeLocalStorage", "<", "GB"),
        # ServerlessDatabaseCapacity: 정의(_AURORA_SERVERLESS_CAPACITY)는 있으나 어떤 변형도 emit하지 않는다 —
        # ACUUtilization이 비율로 대신한다. 옛 태그 호환으로 표시명·기본치만 남긴다.
        "ServerlessDatabaseCapacity": ("ServerlessDatabaseCapacity", ">", "ACU"),
    },
    defaults={
        "CPUUtilization": 80.0,
        "ACUUtilization": 80.0,
        "DatabaseConnections": 100.0,
        "ReplicaLag": 2000000.0,
        "ReaderReplicaLag": 2000000.0,
        "FreeableMemory": 2.0,
        "FreeLocalStorage": 10.0,
        "ServerlessDatabaseCapacity": 128.0,
    },
))
