"""MQ — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_MQ_ALARMS = [
    {
        "metric": "MqCPU",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "CpuUtilization",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "HeapUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "HeapUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "JobSchedulerStoreUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "JobSchedulerStorePercentUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "StoreUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "StorePercentUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="MQ", label="Amazon MQ 브로커", collector="mq",
    rgt_filters=("mq:broker",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateBroker", CREATE), Lifecycle("DeleteBroker", DELETE)),
    notes="TagName `{broker}-{1|2}` — alive 판정이 접미를 떼고 조회한다.",
    alarm_defs=_MQ_ALARMS,
))
