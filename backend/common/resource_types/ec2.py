"""EC2 — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, MODIFY, TAG_CHANGE, Lifecycle, ResourceTypeSpec, register


_EC2_SUBRESOURCE_NOTE = ("RGT 프라임 안 함: ec2 서비스는 스냅숏·ENI·보안그룹 등 하위 리소스 ARN이 수백 개라 프라임 비용이 크고, "
                         "describe_*가 서버 측 태그 필터(Filter=tag:Monitoring)를 지원한다.")

#: EC2 애플리케이션 상태 검사(2026-08 출시)의 인스턴스 단위 집계 지표.
#: AWS가 VPC 내 관리형 ENI로 앱의 HTTP 엔드포인트를 60초마다 찔러 보고 0/1로 발행한다.
APP_STATUS_METRIC_KEY = "StatusCheckFailed_Application"


# EC2 알람 (CPU: AWS/EC2, Memory/Disk: CWAgent)
# CWAgent 미설치 시 Memory/Disk 알람은 INSUFFICIENT_DATA 상태로 대기
_EC2_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/EC2",
        "metric_name": "CPUUtilization",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "mem_used_percent",
        "namespace": "CWAgent",
        "metric_name": "mem_used_percent",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # CWAgent 미설치 시 데이터 없음 = 정상
    },
    {
        "metric": "disk_used_percent",
        "namespace": "CWAgent",
        "metric_name": "disk_used_percent",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        # extra_dimensions는 동적으로 조회 (device/fstype/path는 인스턴스마다 다름)
        "dynamic_dimensions": True,
        "treat_missing_data": "notBreaching",  # CWAgent 미설치 시 데이터 없음 = 정상
    },
    {
        "metric": "StatusCheckFailed",
        "namespace": "AWS/EC2",
        "metric_name": "StatusCheckFailed",
        "dimension_key": "InstanceId",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


_EC2_APP_STATUS_ALARM = {
    "metric": APP_STATUS_METRIC_KEY,
    "namespace": "AWS/EC2",
    "metric_name": APP_STATUS_METRIC_KEY,
    "dimension_key": "InstanceId",
    "stat": "Maximum",
    "comparison": "GreaterThanThreshold",
    # 지표가 1분 주기이고, 디바운스(연속 2회 실패)는 AWS 검사 쪽에 이미 있다.
    # 여기서 M-of-N을 또 얹으면 가용성 장애 감지가 그만큼 늦어진다.
    "period": 60,
    "evaluation_periods": 1,
    # **반드시 notBreaching.** 상태 검사가 연결되지 않은 인스턴스는 이 지표를 아예 발행하지
    # 않는다 — breaching이면 검사를 안 쓰는 인스턴스 전부가 즉시 알람이 된다.
    # (시스템 검사 StatusCheckFailed가 breaching인 것과 반대다.)
    "treat_missing_data": "notBreaching",
    # 태그(Threshold_…)가 있어야 붙는 옵트인 정의 — 기본 메트릭 키 집합(_HARDCODED_METRIC_KEYS)에 넣지 않는다.
    "opt_in": True,
}


def _get_ec2_alarm_defs(resource_tags: dict) -> list[dict]:
    """EC2 알람 정의. 애플리케이션 상태 검사 알람은 **옵트인**한 인스턴스에만 붙인다.

    검사를 만들지 않은 인스턴스는 지표가 없으므로, 기본 생성하면 전 인스턴스에 데이터 없는
    알람이 하나씩 생겨 요금(개당 월 $0.10)만 늘고 얻는 게 없다. `Threshold_...` 태그가 있으면
    켠다 — 값이 `off`면 정의는 남고 하위 경로가 생성을 건너뛰고 기존 알람을 지운다(다른 지표와 동일).
    """
    if (resource_tags or {}).get(f"Threshold_{APP_STATUS_METRIC_KEY}", "").strip():
        return [*_EC2_ALARMS, _EC2_APP_STATUS_ALARM]
    return _EC2_ALARMS


SPEC = register(ResourceTypeSpec(
    type="EC2", label="EC2 인스턴스", collector="ec2",
    rgt_filters=("ec2:instance",), rgt_prime=False,
    lifecycle=(Lifecycle("ModifyInstanceAttribute", MODIFY), Lifecycle("ModifyInstanceType", MODIFY),
               Lifecycle("TerminateInstances", DELETE), Lifecycle("RunInstances", CREATE),
               Lifecycle("CreateTags", TAG_CHANGE), Lifecycle("DeleteTags", TAG_CHANGE)),
    notes=_EC2_SUBRESOURCE_NOTE + " 앱 상태검사 알람은 옵트인(Threshold_StatusCheckFailed_Application). "
          "identity 없음: 나열이 서버 측 태그 필터(Filters=tag:Monitoring)라 RGT가 필요 없다. 메트릭은 수집기 오버라이드 — "
          "CWAgent 메모리·디스크(경로별 list_metrics 디멘션 발견)와 CPU/Memory/Disk_* 결과 키가 임계치 분기에 묶여 있다.",
    alarm_defs=_get_ec2_alarm_defs,
    variants=({}, {f"Threshold_{APP_STATUS_METRIC_KEY}": "1"}),
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "CPUUtilization": ("CPUUtilization", ">", "%"),
        "mem_used_percent": ("mem_used_percent", ">", "%"),
        "disk_used_percent": ("disk_used_percent", ">", "%"),
        "StatusCheckFailed": ("StatusCheckFailed", ">", ""),
        "StatusCheckFailed_Application": ("StatusCheckFailed_Application", ">", ""),
    },
    defaults={
        "CPUUtilization": 80.0,
        "mem_used_percent": 80.0,
        "disk_used_percent": 80.0,
        "StatusCheckFailed": 0.0,
        "StatusCheckFailed_Application": 0.0,
    },
))
