"""ALB — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, MODIFY, TAG_CHANGE, Lifecycle, ResourceTypeSpec, register


_ALB_ALARMS = [
    {
        "metric": "RequestCount",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "RequestCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 트래픽 없으면 데이터 없음
    },
    {
        "metric": "HTTPCode_ELB_5XX_Count",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HTTPCode_ELB_5XX_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 요청 없으면 에러도 없음
    },
    {
        "metric": "TargetResponseTime",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetResponseTime",
        "dimension_key": "LoadBalancer",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 요청 없으면 응답 시간 없음
    },
    {
        "metric": "ELB4XX",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HTTPCode_ELB_4XX_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "TargetConnectionError",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetConnectionErrorCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="ALB", label="Application Load Balancer", collector="elb", aliases=("ELB",),
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyLoadBalancerAttributes", MODIFY, "ELB"), Lifecycle("ModifyListener", MODIFY, "ELB"),
               Lifecycle("DeleteLoadBalancer", DELETE, "ELB"), Lifecycle("CreateLoadBalancer", CREATE, "ELB"),
               Lifecycle("AddTags", TAG_CHANGE, "ELB"), Lifecycle("RemoveTags", TAG_CHANGE, "ELB")),
    notes="LB 이벤트 이름은 ALB/NLB/CLB를 구분하지 않아 target=ELB로 받고 ARN(loadbalancer/app|net)으로 가른다. "
          "필터도 셋이 공유한다. NLB·CLB 스펙은 그래서 lifecycle이 비어 있다.",
    alarm_defs=_ALB_ALARMS,
))
