"""
AWS Monitoring Engine - Common Package

공통 상수, 데이터 모델 정의
"""

from typing import TypedDict

# ──────────────────────────────────────────────
# 상수 정의
# ──────────────────────────────────────────────

# 시스템 하드코딩 기본값 (최종 폴백) - Requirements 2.5
# Disk_* 계열은 'Disk' 단일 키로 폴백
HARDCODED_DEFAULTS: dict[str, float] = {
    "CPU": 80.0,
    "Memory": 80.0,
    "Connections": 100.0,
    "FreeMemoryGB": 2.0,
    "FreeStorageGB": 10.0,
    "Disk": 80.0,
    "RequestCount": 10000.0,
    "HealthyHostCount": 1.0,
    "ProcessedBytes": 100000000.0,
    "ActiveFlowCount": 10000.0,
    "NewFlowCount": 5000.0,
    "StatusCheckFailed": 0.0,
    "ReadLatency": 0.02,
    "WriteLatency": 0.02,
    "ELB5XX": 50.0,
    "TargetResponseTime": 5.0,
    "TCPClientReset": 100.0,
    "TCPTargetReset": 100.0,
    "RequestCountPerTarget": 1000.0,
    "TGResponseTime": 5.0,
    "FreeLocalStorageGB": 10.0,
    "ReplicaLag": 2000000.0,
}

# 지원하는 AWS 리소스 유형 - Requirements 6.1
SUPPORTED_RESOURCE_TYPES: list[str] = ["EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS"]

# CloudTrail 모니터링 대상 API 이벤트 - Requirements 4.1, 8.1, 8.4
MONITORED_API_EVENTS: dict[str, list[str]] = {
    "MODIFY": [
        "ModifyInstanceAttribute",
        "ModifyInstanceType",
        "ModifyDBInstance",
        "ModifyLoadBalancerAttributes",
        "ModifyListener",
    ],
    "DELETE": [
        "TerminateInstances",
        "DeleteDBInstance",
        "DeleteLoadBalancer",
        "DeleteTargetGroup",
    ],
    "TAG_CHANGE": [
        "CreateTags",
        "DeleteTags",
        "AddTagsToResource",       # RDS
        "RemoveTagsFromResource",  # RDS
        "AddTags",                 # ELB
        "RemoveTags",              # ELB
    ],
    "CREATE": [
        "RunInstances",
        "CreateDBInstance",
        "CreateLoadBalancer",
        "CreateTargetGroup",
    ],
}


# ──────────────────────────────────────────────
# TypedDict 데이터 모델 정의
# ──────────────────────────────────────────────

class ResourceInfo(TypedDict):
    """수집된 AWS 리소스 정보"""
    id: str           # 리소스 ID (예: "i-1234567890abcdef0")
    type: str         # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS"
    tags: dict        # {"Monitoring": "on", "Threshold_CPU": "90", ...}
    region: str       # AWS 리전


class AlertMessage(TypedDict):
    """임계치 초과 SNS 알림 메시지"""
    alert_type: str       # "THRESHOLD_EXCEEDED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS"
    metric_name: str      # "CPU" | "Memory" | "Connections" 등
    current_value: float
    threshold: float
    timestamp: str        # ISO 8601
    message: str          # 사람이 읽을 수 있는 요약


class RemediationAlertMessage(TypedDict):
    """Auto-Remediation 완료 SNS 알림 메시지"""
    alert_type: str       # "REMEDIATION_PERFORMED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS"
    change_summary: str   # 감지된 변경 내용 요약
    action_taken: str     # "STOPPED" | "DELETED"
    timestamp: str        # ISO 8601


class LifecycleAlertMessage(TypedDict):
    """리소스 생명주기 변경 SNS 알림 메시지"""
    alert_type: str       # "RESOURCE_DELETED" | "MONITORING_REMOVED"
    resource_id: str
    resource_type: str    # "EC2" | "RDS" | "ALB" | "NLB" | "TG" | "AuroraRDS"
    message: str          # 사람이 읽을 수 있는 요약
    timestamp: str        # ISO 8601
