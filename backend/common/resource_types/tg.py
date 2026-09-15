"""TG — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_TG_ALARMS = [
    {
        "metric": "HealthyHostCount",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HealthyHostCount",
        "dimension_key": "TargetGroup",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "UnHealthyHostCount",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "UnHealthyHostCount",
        "dimension_key": "TargetGroup",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 건강한 상태에서 0으로 발행, 실제 missing은 드묾
    },
    {
        "metric": "RequestCountPerTarget",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "RequestCountPerTarget",
        "dimension_key": "TargetGroup",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 요청 없으면 데이터 없음
    },
    {
        "metric": "TargetResponseTime",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetResponseTime",
        "dimension_key": "TargetGroup",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 요청 없으면 데이터 없음
    },
]


_NLB_TG_EXCLUDED_METRICS = {"RequestCountPerTarget", "TargetResponseTime"}


def _get_tg_alarm_defs(resource_tags: dict) -> list[dict]:
    """대상그룹 변형.

    TargetType=alb인 TG는 HealthyHostCount/UnHealthyHostCount를 CloudWatch가 발행하지 않는다(AWS 제약)
    → 알람 없음. NLB 대상그룹은 요청 수·응답 시간 지표가 없다.
    """
    if resource_tags.get("_target_type") == "alb":
        return []
    if resource_tags.get("_lb_type") == "network":
        return [d for d in _TG_ALARMS if d["metric"] not in _NLB_TG_EXCLUDED_METRICS]
    return _TG_ALARMS


SPEC = register(ResourceTypeSpec(
    type="TG", label="대상 그룹", collector="elb",
    rgt_filters=("elasticloadbalancing:targetgroup",), rgt_prime=True,
    lifecycle=(Lifecycle("DeleteTargetGroup", DELETE), Lifecycle("CreateTargetGroup", CREATE)),
    notes="NLB 대상그룹은 네임스페이스가 AWS/NetworkELB(빌드 시 해석기), TargetType=alb는 알람 없음. LB 계층·short-id 역매핑 때문에 나열은 elb 수집기. "
          "identity 없음: 연결된 LB의 ARN·종류(_lb_arn·_lb_type)는 describe_target_groups(LoadBalancerArn)로만 안다.",
    alarm_defs=_get_tg_alarm_defs,
    variants=({}, {"_lb_type": "network"}, {"_target_type": "alb"}),
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "HealthyHostCount": ("HealthyHostCount", "<", ""),
        "UnHealthyHostCount": ("UnHealthyHostCount", ">", ""),
        "RequestCountPerTarget": ("RequestCountPerTarget", ">", ""),
        "TargetResponseTime": ("TargetResponseTime", ">", "s"),
    },
    defaults={
        "HealthyHostCount": 1.0,
        "UnHealthyHostCount": 1.0,
        "RequestCountPerTarget": 1000.0,
        "TargetResponseTime": 5.0,
    },
))
