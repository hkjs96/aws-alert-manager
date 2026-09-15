"""EFS — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, arn_tail, register


_EFS_ALARMS = [
    {
        "metric": "BurstCreditBalance",
        "namespace": "AWS/EFS",
        "metric_name": "BurstCreditBalance",
        "dimension_key": "FileSystemId",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "PercentIOLimit",
        "namespace": "AWS/EFS",
        "metric_name": "PercentIOLimit",
        "dimension_key": "FileSystemId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "EFSClientConnections",
        "namespace": "AWS/EFS",
        "metric_name": "ClientConnections",
        "dimension_key": "FileSystemId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="EFS", label="EFS 파일 시스템", collector="efs",
    rgt_filters=("elasticfilesystem:file-system",), rgt_prime=True, identity=arn_tail("/"),
    lifecycle=(Lifecycle("CreateFileSystem", CREATE), Lifecycle("DeleteFileSystem", DELETE)),
    notes="P3(2026-09-15)에서 프라임 켬 — 범용 수집기가 태그 캐시로 나열한다(그 전엔 describe 응답의 Tags를 읽어 캐시를 안 썼다).",
    alarm_defs=_EFS_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "BurstCreditBalance": ("BurstCreditBalance", "<", ""),
        "PercentIOLimit": ("PercentIOLimit", ">", "%"),
        "EFSClientConnections": ("ClientConnections", ">", ""),
    },
    defaults={
        "BurstCreditBalance": 1000000000.0,
        "PercentIOLimit": 90.0,
        "EFSClientConnections": 1000.0,
    },
))
