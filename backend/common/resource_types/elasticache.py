"""ElastiCache — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, MODIFY, Lifecycle, ResourceTypeSpec, register


_ELASTICACHE_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/ElastiCache",
        "metric_name": "CPUUtilization",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "EngineCPU",
        "namespace": "AWS/ElastiCache",
        "metric_name": "EngineCPUUtilization",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseMemoryUsagePercentage",
        "namespace": "AWS/ElastiCache",
        "metric_name": "DatabaseMemoryUsagePercentage",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "Evictions",
        "namespace": "AWS/ElastiCache",
        "metric_name": "Evictions",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "CurrConnections",
        "namespace": "AWS/ElastiCache",
        "metric_name": "CurrConnections",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="ElastiCache", label="ElastiCache", collector="elasticache",
    rgt_filters=("elasticache:cluster",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyCacheCluster", MODIFY), Lifecycle("DeleteCacheCluster", DELETE),
               Lifecycle("CreateCacheCluster", CREATE)),
    alarm_defs=_ELASTICACHE_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CPUUtilization": ("CPUUtilization", ">", "%"),
        "EngineCPU": ("EngineCPUUtilization", ">=", "%"),
        "DatabaseMemoryUsagePercentage": ("DatabaseMemoryUsagePercentage", ">=", "%"),
        "Evictions": ("Evictions", ">=", ""),
        "CurrConnections": ("CurrConnections", ">=", ""),
    },
    defaults={
        "CPUUtilization": 80.0,
        "EngineCPU": 90.0,
        "DatabaseMemoryUsagePercentage": 80.0,
        "Evictions": 5.0,
        "CurrConnections": 200.0,
    },
))
