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
    "UnHealthyHostCount": 1.0,
    "ProcessedBytes": 100000000.0,
    "ActiveFlowCount": 10000.0,
    "NewFlowCount": 5000.0,
    "StatusCheckFailed": 0.0,
    "ReadLatency": 0.02,
    "WriteLatency": 0.02,
    "ELB5XX": 50.0,
    "ELB4XX": 100.0,
    "TargetConnectionError": 50.0,
    "TargetResponseTime": 5.0,
    "TCPClientReset": 100.0,
    "TCPTargetReset": 100.0,
    "RequestCountPerTarget": 1000.0,
    "TGResponseTime": 5.0,
    "FreeLocalStorageGB": 10.0,
    "ReplicaLag": 2000000.0,
    "ReaderReplicaLag": 2000000.0,
    "ACUUtilization": 80.0,
    "ServerlessDatabaseCapacity": 128.0,
    "FreeMemoryPct": 20.0,
    "FreeLocalStoragePct": 20.0,
    "ConnectionAttempts": 500.0,
    "EngineCPU": 90.0,
    "SwapUsage": 1.0,
    "Evictions": 5.0,
    "CurrConnections": 200.0,
    "PacketsDropCount": 1.0,
    "ErrorPortAllocation": 1.0,
    "Duration": 2500.0,
    "Errors": 0.0,
    "TunnelState": 1.0,
    "ApiLatency": 3000.0,
    "Api4XXError": 1.0,
    "Api5XXError": 1.0,
    "Api4xx": 1.0,
    "Api5xx": 1.0,
    "WsConnectCount": 1000.0,
    "WsMessageCount": 10000.0,
    "WsIntegrationError": 0.0,
    "WsExecutionError": 0.0,
    "DaysToExpiry": 14.0,
    "BackupJobsFailed": 0.0,
    "BackupJobsAborted": 0.0,
    "MqCPU": 90.0,
    "HeapUsage": 80.0,
    "JobSchedulerStoreUsage": 80.0,
    "StoreUsage": 80.0,
    "CLBUnHealthyHost": 0.0,
    "CLB5XX": 300.0,
    "CLB4XX": 300.0,
    "CLBBackend5XX": 300.0,
    "CLBBackend4XX": 300.0,
    "SurgeQueueLength": 300.0,
    "SpilloverCount": 300.0,
    "ClusterStatusRed": 0.0,
    "ClusterStatusYellow": 0.0,
    "OSFreeStorageSpace": 20480.0,
    "ClusterIndexWritesBlocked": 0.0,
    "OsCPU": 80.0,
    "JVMMemoryPressure": 80.0,
    "MasterCPU": 50.0,
    "MasterJVMMemoryPressure": 80.0,
    "SQSMessagesVisible": 1000.0,
    "SQSOldestMessage": 300.0,
    "SQSMessagesSent": 10000.0,
    "EcsCPU": 80.0,
    "EcsMemory": 80.0,
    "OffsetLag": 1000.0,
    "BytesInPerSec": 100000000.0,
    "UnderReplicatedPartitions": 0.0,
    "ActiveControllerCount": 1.0,
    "DDBReadCapacity": 80.0,
    "DDBWriteCapacity": 80.0,
    "ThrottledRequests": 0.0,
    "DDBSystemErrors": 0.0,
    "CF5xxErrorRate": 1.0,
    "CF4xxErrorRate": 5.0,
    "CFRequests": 1000000.0,
    "CFBytesDownloaded": 10000000000.0,
    "WAFBlockedRequests": 100.0,
    "WAFAllowedRequests": 1000000.0,
    "WAFCountedRequests": 100000.0,
    "HealthCheckStatus": 1.0,
    "ConnectionState": 1.0,
    "BurstCreditBalance": 1000000000.0,
    "PercentIOLimit": 90.0,
    "EFSClientConnections": 1000.0,
    "S34xxErrors": 100.0,
    "S35xxErrors": 10.0,
    "S3BucketSizeBytes": 1000000000000.0,
    "S3NumberOfObjects": 10000000.0,
    "SMInvocations": 100000.0,
    "SMInvocationErrors": 0.0,
    "SMModelLatency": 1000.0,
    "SMCPU": 80.0,
    "SNSNotificationsFailed": 0.0,
    "SNSMessagesPublished": 1000000.0,
}

# 지원하는 AWS 리소스 유형 - Requirements 6.1
SUPPORTED_RESOURCE_TYPES: list[str] = [
    "EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS", "DocDB", "ElastiCache", "NAT",
    "Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch",
    "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
    "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
]

# CloudTrail 모니터링 대상 API 이벤트 - Requirements 4.1, 8.1, 8.4
MONITORED_API_EVENTS: dict[str, list[str]] = {
    "MODIFY": [
        "ModifyInstanceAttribute",
        "ModifyInstanceType",
        "ModifyDBInstance",
        "ModifyLoadBalancerAttributes",
        "ModifyListener",
        "ModifyCacheCluster",
    ],
    "DELETE": [
        "TerminateInstances",
        "DeleteDBInstance",
        "DeleteLoadBalancer",
        "DeleteTargetGroup",
        "DeleteCacheCluster",
        "DeleteNatGateway",
        "DeleteFunction20150331",   # Lambda
        "DeleteVpnConnection",      # VPN
        "DeleteRestApi",            # APIGW REST
        "DeleteApi",                # APIGW v2
        "DeleteCertificate",        # ACM
        "DeleteBackupVault",        # Backup
        "DeleteBroker",             # MQ
        "DeleteDomain",             # OpenSearch
        "DeleteQueue",              # SQS
        "DeleteService",            # ECS
        "DeleteCluster",            # MSK
        "DeleteTable",              # DynamoDB
        "DeleteDistribution",       # CloudFront
        "DeleteWebACL",             # WAF
        "DeleteHealthCheck",        # Route53
        "DeleteConnection",         # DX
        "DeleteFileSystem",         # EFS
        "DeleteBucket",             # S3
        "DeleteEndpoint",           # SageMaker
        "DeleteTopic",              # SNS
    ],
    "TAG_CHANGE": [
        "CreateTags",
        "DeleteTags",
        "AddTagsToResource",       # RDS
        "RemoveTagsFromResource",  # RDS
        "AddTags",                 # ELB
        "RemoveTags",              # ELB
        "TagResource",             # Lambda, APIGW, ACM, Backup, MQ, OpenSearch, ECS, MSK, DynamoDB, EFS, SageMaker, SNS
        "UntagResource",           # Lambda, APIGW, ACM, Backup, MQ, OpenSearch, ECS, MSK, DynamoDB, EFS, SageMaker, SNS
        "TagQueue",                # SQS
        "UntagQueue",              # SQS
    ],
    "CREATE": [
        "RunInstances",
        "CreateDBInstance",
        "CreateLoadBalancer",
        "CreateTargetGroup",
        "CreateCacheCluster",
        "CreateNatGateway",
        "CreateFunction20150331",   # Lambda
        "CreateRestApi",            # APIGW REST
        "CreateApi",                # APIGW v2
        "CreateBackupVault",        # Backup
        "CreateBroker",             # MQ
        "CreateDomain",             # OpenSearch
        "CreateQueue",              # SQS
        "CreateService",            # ECS
        "CreateCluster",            # MSK
        "CreateTable",              # DynamoDB
        "CreateDistribution",       # CloudFront
        "CreateWebACL",             # WAF
        "CreateHealthCheck",        # Route53
        "CreateConnection",         # DX
        "CreateFileSystem",         # EFS
        "CreateBucket",             # S3
        "CreateEndpoint",           # SageMaker
        "CreateTopic",              # SNS
    ],
}


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
