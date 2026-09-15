"""VPN — 리소스 타입 스펙 (docs/specs/resource-type-registry)

알람 정의·태그 조건부 변형·생명주기·나열 힌트가 전부 이 파일에 있다. 타입을 고칠 때 여기만 고친다 —
`SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`MONITORED_API_EVENTS`·수집기 맵은 파생된다.
"""

from __future__ import annotations

from common.resource_types.base import DELETE, Lifecycle, ResourceTypeSpec, register
from common.resource_types.ec2 import _EC2_SUBRESOURCE_NOTE


_VPN_ALARMS = [
    {
        "metric": "TunnelState",
        "namespace": "AWS/VPN",
        "metric_name": "TunnelState",
        "dimension_key": "VpnId",
        "stat": "Maximum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]


SPEC = register(ResourceTypeSpec(
    type="VPN", label="Site-to-Site VPN", collector="vpn",
    rgt_filters=("ec2:vpn-connection",), rgt_prime=False,
    lifecycle=(Lifecycle("DeleteVpnConnection", DELETE),),
    notes=_EC2_SUBRESOURCE_NOTE,
    alarm_defs=_VPN_ALARMS,
))
