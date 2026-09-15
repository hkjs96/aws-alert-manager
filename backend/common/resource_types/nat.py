"""NAT — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import CREATE, DELETE, Lifecycle, ResourceTypeSpec, register
from common.resource_types.ec2 import _EC2_SUBRESOURCE_NOTE


_NATGW_ALARMS = [
    {
        "metric": "PacketsDropCount",
        "namespace": "AWS/NATGateway",
        "metric_name": "PacketsDropCount",
        "dimension_key": "NatGatewayId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 패킷 드롭 없으면 0으로 발행
    },
    {
        "metric": "ErrorPortAllocation",
        "namespace": "AWS/NATGateway",
        "metric_name": "ErrorPortAllocation",
        "dimension_key": "NatGatewayId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 포트 할당 오류 없으면 0으로 발행
    },
]


SPEC = register(ResourceTypeSpec(
    type="NAT", label="NAT Gateway", collector="natgw", aliases=("NATGateway",),
    rgt_filters=("ec2:natgateway",), rgt_prime=False,
    lifecycle=(Lifecycle("DeleteNatGateway", DELETE), Lifecycle("CreateNatGateway", CREATE)),
    notes=_EC2_SUBRESOURCE_NOTE + " natgw 수집기가 이미 서버 측 필터를 쓴다 — 다른 EC2 계열이 따라갈 본보기.",
    alarm_defs=_NATGW_ALARMS,
    # 표시명(알람 이름에 쓰는 지표명·방향·단위)과 기본 임계치 — 옛 alarm_registry._METRIC_DISPLAY / common.HARDCODED_DEFAULTS.
    # 여러 타입이 같은 키(CPUUtilization 등)를 선언하면 값이 같아야 한다 — 뷰가 강제한다.
    display={
        "PacketsDropCount": ("PacketsDropCount", ">", ""),
        "ErrorPortAllocation": ("ErrorPortAllocation", ">", ""),
    },
    defaults={
        "PacketsDropCount": 1.0,
        "ErrorPortAllocation": 1.0,
    },
))
