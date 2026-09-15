"""DX — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register


_DX_ALARMS = [
    {
        "metric": "ConnectionState",
        "namespace": "AWS/DX",
        "metric_name": "ConnectionState",
        "dimension_key": "ConnectionId",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="DX", label="Direct Connect", collector="dx",
    rgt_filters=("directconnect:dxcon",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateConnection", CREATE), Lifecycle("DeleteConnection", DELETE)),
    notes=("identity 없음: connectionState=available 필터에 describe_connections가 어차피 필요하고 태그는 캐시에서 읽으므로 "
           "RGT 나열로 아낄 콜이 없다 — 수집기의 describe 나열만 쓴다."),
    alarm_defs=_DX_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "ConnectionState": ("ConnectionState", "<", ""),
    },
    defaults={
        "ConnectionState": 1.0,
    },
))
