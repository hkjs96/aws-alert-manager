"""NLB — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import ResourceTypeSpec, register


_NLB_ALARMS = [
    {
        "metric": "ProcessedBytes",
        "namespace": "AWS/NetworkELB",
        "metric_name": "ProcessedBytes",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 트래픽 없으면 데이터 없음
    },
    {
        "metric": "ActiveFlowCount",
        "namespace": "AWS/NetworkELB",
        "metric_name": "ActiveFlowCount",
        "dimension_key": "LoadBalancer",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 활성 연결 없으면 데이터 없음
    },
    {
        "metric": "NewFlowCount",
        "namespace": "AWS/NetworkELB",
        "metric_name": "NewFlowCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "TCP_Client_Reset_Count",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Client_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "TCP_Target_Reset_Count",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Target_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="NLB", label="Network Load Balancer", collector="elb",
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    notes="생명주기 이벤트는 ALB 스펙(target=ELB)에 — 이벤트 이름이 LB 종류를 구분하지 않는다. identity 없음: 나열·메트릭은 elb 수집기(ALB 스펙 notes).",
    alarm_defs=_NLB_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "ProcessedBytes": ("ProcessedBytes", ">", ""),
        "ActiveFlowCount": ("ActiveFlowCount", ">", ""),
        "NewFlowCount": ("NewFlowCount", ">", ""),
        "TCP_Client_Reset_Count": ("TCP_Client_Reset_Count", ">", ""),
        "TCP_Target_Reset_Count": ("TCP_Target_Reset_Count", ">", ""),
    },
    defaults={
        "ProcessedBytes": 100000000.0,
        "ActiveFlowCount": 10000.0,
        "NewFlowCount": 5000.0,
        "TCP_Client_Reset_Count": 100.0,
        "TCP_Target_Reset_Count": 100.0,
    },
))
