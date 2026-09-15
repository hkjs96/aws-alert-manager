"""OpenSearch — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_OPENSEARCH_ALARMS = [
    {
        "metric": "ClusterStatusRed",
        "namespace": "AWS/ES",
        "metric_name": "ClusterStatus.red",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "ClusterStatusYellow",
        "namespace": "AWS/ES",
        "metric_name": "ClusterStatus.yellow",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "OSFreeStorageSpace",
        "namespace": "AWS/ES",
        "metric_name": "FreeStorageSpace",
        "dimension_key": "DomainName",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "ClusterIndexWritesBlocked",
        "namespace": "AWS/ES",
        "metric_name": "ClusterIndexWritesBlocked",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "OsCPU",
        "namespace": "AWS/ES",
        "metric_name": "CPUUtilization",
        "dimension_key": "DomainName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "JVMMemoryPressure",
        "namespace": "AWS/ES",
        "metric_name": "JVMMemoryPressure",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "MasterCPU",
        "namespace": "AWS/ES",
        "metric_name": "MasterCPUUtilization",
        "dimension_key": "DomainName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "MasterJVMMemoryPressure",
        "namespace": "AWS/ES",
        "metric_name": "MasterJVMMemoryPressure",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
]


SPEC = register(ResourceTypeSpec(
    type="OpenSearch", label="OpenSearch 도메인", collector="opensearch",
    rgt_filters=("es:domain",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateDomain", CREATE), Lifecycle("DeleteDomain", DELETE)),
    alarm_defs=_OPENSEARCH_ALARMS,
))
