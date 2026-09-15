"""
타입에 속하지 않는 표시명·기본 임계치 — 옛 태그 키와 퍼센트 변형 (docs/specs/resource-type-registry P2.4b)

메트릭 키 개명(Phase 4 Task 16) 전에는 태그가 `Threshold_CPU`·`Threshold_FreeMemoryGB`처럼 친숙한 이름을 썼다.
고객 리소스에 그 태그가 그대로 남아 있으므로 계속 읽어야 한다(`tag_resolver._LEGACY_TAG_MAP`이 CloudWatch 이름 →
옛 키를 잇는다). 새 코드는 이 키를 쓰지 않는다 — 여기 있는 것은 전부 **호환**이다.

옛 표(`HARDCODED_DEFAULTS`)에는 이 항목들이 타입 키와 섞여 있었고 왜 있는지 적혀 있지 않았다. 여기서는
항목마다 이유가 붙고, `shared_threshold_reasons()`로 읽을 수 있다.
"""

from common.resource_types.base import add_shared_thresholds

add_shared_thresholds(
    reason=("메트릭 키 개명(Phase 4 Task 16) 전의 친숙한 태그 키 — 고객 리소스에 남은 Threshold_CPU 류 태그를 계속 읽는다"
            "(tag_resolver._LEGACY_TAG_MAP). 새 코드는 쓰지 않는다."),
    display={
        "CPU": ("CPUUtilization", ">", "%"),
        "Connections": ("DatabaseConnections", ">", ""),
        "ELB5XX": ("HTTPCode_ELB_5XX_Count", ">", ""),
        "FreeLocalStorageGB": ("FreeLocalStorage", "<", "GB"),
        "FreeMemoryGB": ("FreeableMemory", "<", "GB"),
        "FreeStorageGB": ("FreeStorageSpace", "<", "GB"),
        "Memory": ("mem_used_percent", ">", "%"),
        "TCPClientReset": ("TCP_Client_Reset_Count", ">", ""),
        "TCPTargetReset": ("TCP_Target_Reset_Count", ">", ""),
        "TGResponseTime": ("TargetResponseTime", ">", "s"),
    },
    defaults={
        "CPU": 80.0,
        "Connections": 100.0,
        "Disk": 80.0,
        "ELB5XX": 50.0,
        "FreeLocalStorageGB": 10.0,
        "FreeMemoryGB": 2.0,
        "FreeStorageGB": 10.0,
        "Memory": 80.0,
        "TCPClientReset": 100.0,
        "TCPTargetReset": 100.0,
        "TGResponseTime": 5.0,
    },
)

add_shared_thresholds(
    reason=("절대값(FreeableMemory·FreeLocalStorage) 대신 인스턴스 사양 대비 %로 해석하는 태그 — threshold_resolver가 "
            "_total_*_bytes 내부 태그와 함께 쓴다."),
    defaults={
        "FreeLocalStoragePct": 20.0,
        "FreeMemoryPct": 20.0,
    },
)
