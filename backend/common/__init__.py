"""
AWS Monitoring Engine - Common Package

공통 상수, 데이터 모델 정의
"""

from typing import TypedDict

# ──────────────────────────────────────────────
# 상수 정의
# ──────────────────────────────────────────────

# 지원 타입·기본 임계치·CloudTrail 이벤트 목록은 리소스 타입 레지스트리에서 파생된다 (docs/specs/resource-type-registry).
# 레지스트리 패키지는 표준 라이브러리만 의존하므로 이 모듈 초기화 중에 import해도 순환이 없다.
from common.resource_types import (  # noqa: E402
    hardcoded_defaults as _registry_hardcoded_defaults,
    monitored_api_events as _registry_monitored_api_events,
    types as _registry_types,
)

# 시스템 하드코딩 기본값 (최종 폴백) - Requirements 2.5. Disk_* 계열은 'Disk' 단일 키로 폴백.
# 타입별 값은 각 `common/resource_types/<type>.py`의 `defaults`, 옛 태그 키는 `legacy.py`(이유 포함).
HARDCODED_DEFAULTS: dict[str, float] = _registry_hardcoded_defaults()

# 지원하는 AWS 리소스 유형 - Requirements 6.1 (레지스트리 등록 순서)
SUPPORTED_RESOURCE_TYPES: list[str] = _registry_types()

# CloudTrail 모니터링 대상 API 이벤트 - Requirements 4.1, 8.1, 8.4 (스펙의 lifecycle + 공유 이벤트)
MONITORED_API_EVENTS: dict[str, list[str]] = _registry_monitored_api_events()


# ──────────────────────────────────────────────
# TypedDict 데이터 모델 정의
# ──────────────────────────────────────────────

class ResourceInfo(TypedDict):
    """수집된 AWS 리소스 정보"""
    id: str           # 리소스 ID (예: "i-1234567890abcdef0")
    type: str         # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS" | "DocDB"
    tags: dict        # {"Monitoring": "on", "Threshold_CPU": "90", ...}
    region: str       # AWS 리전


class AlertMessage(TypedDict):
    """임계치 초과 SNS 알림 메시지"""
    alert_type: str       # "THRESHOLD_EXCEEDED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS" | "DocDB"
    metric_name: str      # "CPU" | "Memory" | "Connections" 등
    current_value: float
    threshold: float
    timestamp: str        # ISO 8601
    message: str          # 사람이 읽을 수 있는 요약


class RemediationAlertMessage(TypedDict):
    """Auto-Remediation 완료 SNS 알림 메시지"""
    alert_type: str       # "REMEDIATION_PERFORMED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS" | "DocDB"
    change_summary: str   # 감지된 변경 내용 요약
    action_taken: str     # "STOPPED" | "DELETED"
    timestamp: str        # ISO 8601


class LifecycleAlertMessage(TypedDict):
    """리소스 생명주기 변경 SNS 알림 메시지"""
    alert_type: str       # "RESOURCE_DELETED" | "MONITORING_REMOVED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS" | "DocDB"
    message: str          # 사람이 읽을 수 있는 요약
    timestamp: str        # ISO 8601
