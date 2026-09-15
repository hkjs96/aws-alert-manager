"""MSK — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_MSK_ALARMS = [
    {
        "metric": "OffsetLag",
        "namespace": "AWS/Kafka",
        "metric_name": "SumOffsetLag",
        "dimension_key": "Cluster Name",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "BytesInPerSec",
        "namespace": "AWS/Kafka",
        "metric_name": "BytesInPerSec",
        "dimension_key": "Cluster Name",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "UnderReplicatedPartitions",
        "namespace": "AWS/Kafka",
        "metric_name": "UnderReplicatedPartitions",
        "dimension_key": "Cluster Name",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "ActiveControllerCount",
        "namespace": "AWS/Kafka",
        "metric_name": "ActiveControllerCount",
        "dimension_key": "Cluster Name",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="MSK", label="MSK 클러스터", collector="msk",
    rgt_filters=("kafka:cluster",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateCluster", CREATE), Lifecycle("DeleteCluster", DELETE)),
    alarm_defs=_MSK_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "OffsetLag": ("SumOffsetLag", ">", ""),
        "BytesInPerSec": ("BytesInPerSec", ">", "B/s"),
        "UnderReplicatedPartitions": ("UnderReplicatedPartitions", ">", ""),
        "ActiveControllerCount": ("ActiveControllerCount", "<", ""),
    },
    defaults={
        "OffsetLag": 1000.0,
        "BytesInPerSec": 100000000.0,
        "UnderReplicatedPartitions": 0.0,
        "ActiveControllerCount": 1.0,
    },
))
