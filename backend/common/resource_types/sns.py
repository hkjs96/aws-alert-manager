"""SNS — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_SNS_ALARMS = [
    {
        "metric": "SNSNotificationsFailed",
        "namespace": "AWS/SNS",
        "metric_name": "NumberOfNotificationsFailed",
        "dimension_key": "TopicName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SNSMessagesPublished",
        "namespace": "AWS/SNS",
        "metric_name": "NumberOfMessagesPublished",
        "dimension_key": "TopicName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


SPEC = register(ResourceTypeSpec(
    type="SNS", label="SNS 토픽", collector="sns",
    rgt_filters=("sns",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateTopic", CREATE), Lifecycle("DeleteTopic", DELETE)),
    alarm_defs=_SNS_ALARMS,
))
