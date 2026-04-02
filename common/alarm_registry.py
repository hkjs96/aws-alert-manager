"""
Alarm Registry — 데이터 드리븐 알람 정의 레지스트리

모든 리소스 유형별 알람 정의, 매핑 테이블, 메트릭 키 변환을 단일 모듈로 관리한다.
순수 데이터 모듈로 외부 의존성 없음.
"""

import logging

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 메트릭별 표시이름/방향/단위 매핑
# ──────────────────────────────────────────────

_METRIC_DISPLAY = {
    "CPU": ("CPUUtilization", ">", "%"),
    "Memory": ("mem_used_percent", ">", "%"),
    "Disk": ("disk_used_percent", ">", "%"),
    "FreeMemoryGB": ("FreeableMemory", "<", "GB"),
    "FreeStorageGB": ("FreeStorageSpace", "<", "GB"),
    "Connections": ("DatabaseConnections", ">", ""),
    "RequestCount": ("RequestCount", ">", ""),
    "HealthyHostCount": ("HealthyHostCount", "<", ""),
    "UnHealthyHostCount": ("UnHealthyHostCount", ">", ""),
    "ProcessedBytes": ("ProcessedBytes", ">", ""),
    "ActiveFlowCount": ("ActiveFlowCount", ">", ""),
    "NewFlowCount": ("NewFlowCount", ">", ""),
    "StatusCheckFailed": ("StatusCheckFailed", ">", ""),
    "ReadLatency": ("ReadLatency", ">", "s"),
    "WriteLatency": ("WriteLatency", ">", "s"),
    "ELB5XX": ("HTTPCode_ELB_5XX_Count", ">", ""),
    "ELB4XX": ("HTTPCode_ELB_4XX_Count", ">", ""),
    "TargetConnectionError": ("TargetConnectionErrorCount", ">", ""),
    "TargetResponseTime": ("TargetResponseTime", ">", "s"),
    "TCPClientReset": ("TCP_Client_Reset_Count", ">", ""),
    "TCPTargetReset": ("TCP_Target_Reset_Count", ">", ""),
    "RequestCountPerTarget": ("RequestCountPerTarget", ">", ""),
    "TGResponseTime": ("TargetResponseTime", ">", "s"),
    "FreeLocalStorageGB": ("FreeLocalStorage", "<", "GB"),
    "ReplicaLag": ("AuroraReplicaLagMaximum", ">", "μs"),
    "ReaderReplicaLag": ("AuroraReplicaLag", ">", "μs"),
    "ACUUtilization": ("ACUUtilization", ">", "%"),
    "ServerlessDatabaseCapacity": ("ServerlessDatabaseCapacity", ">", "ACU"),
    "ConnectionAttempts": ("ConnectionAttempts", ">", ""),
    "EngineCPU": ("EngineCPUUtilization", ">=", "%"),
    "SwapUsage": ("SwapUsage", ">=", ""),
    "Evictions": ("Evictions", ">=", ""),
    "CurrConnections": ("CurrConnections", ">=", ""),
    "PacketsDropCount": ("PacketsDropCount", ">", ""),
    "ErrorPortAllocation": ("ErrorPortAllocation", ">", ""),
    "Duration": ("Duration", ">", "ms"),
    "Errors": ("Errors", ">", ""),
    "TunnelState": ("TunnelState", "<", ""),
    "ApiLatency": ("Latency", ">", "ms"),
    "Api4XXError": ("4XXError", ">", ""),
    "Api5XXError": ("5XXError", ">", ""),
    "Api4xx": ("4xx", ">", ""),
    "Api5xx": ("5xx", ">", ""),
    "WsConnectCount": ("ConnectCount", ">", ""),
    "WsMessageCount": ("MessageCount", ">", ""),
    "WsIntegrationError": ("IntegrationError", ">", ""),
    "WsExecutionError": ("ExecutionError", ">", ""),
    "DaysToExpiry": ("DaysToExpiry", "<", "days"),
    "BackupJobsFailed": ("NumberOfBackupJobsFailed", ">", ""),
    "BackupJobsAborted": ("NumberOfBackupJobsAborted", ">", ""),
    "MqCPU": ("CpuUtilization", ">", "%"),
    "HeapUsage": ("HeapUsage", ">", "%"),
    "JobSchedulerStoreUsage": ("JobSchedulerStorePercentUsage", ">", "%"),
    "StoreUsage": ("StorePercentUsage", ">", "%"),
    "CLBUnHealthyHost": ("UnHealthyHostCount", ">", ""),
    "CLB5XX": ("HTTPCode_ELB_5XX", ">", ""),
    "CLB4XX": ("HTTPCode_ELB_4XX", ">", ""),
    "CLBBackend5XX": ("HTTPCode_Backend_5XX", ">", ""),
    "CLBBackend4XX": ("HTTPCode_Backend_4XX", ">", ""),
    "SurgeQueueLength": ("SurgeQueueLength", ">", ""),
    "SpilloverCount": ("SpilloverCount", ">", ""),
    "ClusterStatusRed": ("ClusterStatus.red", ">", ""),
    "ClusterStatusYellow": ("ClusterStatus.yellow", ">", ""),
    "OSFreeStorageSpace": ("FreeStorageSpace", "<", "MB"),
    "ClusterIndexWritesBlocked": ("ClusterIndexWritesBlocked", ">", ""),
    "OsCPU": ("CPUUtilization", ">", "%"),
    "JVMMemoryPressure": ("JVMMemoryPressure", ">", "%"),
    "MasterCPU": ("MasterCPUUtilization", ">", "%"),
    "MasterJVMMemoryPressure": ("MasterJVMMemoryPressure", ">", "%"),
    "SQSMessagesVisible": ("ApproximateNumberOfMessagesVisible", ">", ""),
    "SQSOldestMessage": ("ApproximateAgeOfOldestMessage", ">", "s"),
    "SQSMessagesSent": ("NumberOfMessagesSent", ">", ""),
    "EcsCPU": ("CPUUtilization", ">", "%"),
    "EcsMemory": ("MemoryUtilization", ">", "%"),
    "RunningTaskCount": ("RunningTaskCount", "<", ""),
    "OffsetLag": ("SumOffsetLag", ">", ""),
    "BytesInPerSec": ("BytesInPerSec", ">", "B/s"),
    "UnderReplicatedPartitions": ("UnderReplicatedPartitions", ">", ""),
    "ActiveControllerCount": ("ActiveControllerCount", "<", ""),
    "DDBReadCapacity": ("ConsumedReadCapacityUnits", ">", ""),
    "DDBWriteCapacity": ("ConsumedWriteCapacityUnits", ">", ""),
    "ThrottledRequests": ("ThrottledRequests", ">", ""),
    "DDBSystemErrors": ("SystemErrors", ">", ""),
    "CF5xxErrorRate": ("5xxErrorRate", ">", "%"),
    "CF4xxErrorRate": ("4xxErrorRate", ">", "%"),
    "CFRequests": ("Requests", ">", ""),
    "CFBytesDownloaded": ("BytesDownloaded", ">", "B"),
    "WAFBlockedRequests": ("BlockedRequests", ">", ""),
    "WAFAllowedRequests": ("AllowedRequests", ">", ""),
    "WAFCountedRequests": ("CountedRequests", ">", ""),
    "HealthCheckStatus": ("HealthCheckStatus", "<", ""),
    "ConnectionState": ("ConnectionState", "<", ""),
    "BurstCreditBalance": ("BurstCreditBalance", "<", ""),
    "PercentIOLimit": ("PercentIOLimit", ">", "%"),
    "EFSClientConnections": ("ClientConnections", ">", ""),
    "S34xxErrors": ("4xxErrors", ">", ""),
    "S35xxErrors": ("5xxErrors", ">", ""),
    "S3BucketSizeBytes": ("BucketSizeBytes", ">", "B"),
    "S3NumberOfObjects": ("NumberOfObjects", ">", ""),
    "SMInvocations": ("Invocations", ">", ""),
    "SMInvocationErrors": ("InvocationErrors", ">", ""),
    "SMModelLatency": ("ModelLatency", ">", "μs"),
    "SMCPU": ("CPUUtilization", ">", "%"),
    "SNSNotificationsFailed": ("NumberOfNotificationsFailed", ">", ""),
    "SNSMessagesPublished": ("NumberOfMessagesPublished", ">", ""),
}


# ──────────────────────────────────────────────
# 리소스 유형별 알람 정의
# ──────────────────────────────────────────────

# EC2 알람 (CPU: AWS/EC2, Memory/Disk: CWAgent)
# CWAgent 미설치 시 Memory/Disk 알람은 INSUFFICIENT_DATA 상태로 대기
_EC2_ALARMS = [
    {
        "metric": "CPU",
        "namespace": "AWS/EC2",
        "metric_name": "CPUUtilization",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Memory",
        "namespace": "CWAgent",
        "metric_name": "mem_used_percent",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Disk",
        "namespace": "CWAgent",
        "metric_name": "disk_used_percent",
        "dimension_key": "InstanceId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        # extra_dimensions는 동적으로 조회 (device/fstype/path는 인스턴스마다 다름)
        "dynamic_dimensions": True,
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
    },
]

_RDS_ALARMS = [
    {
        "metric": "CPU",
        "namespace": "AWS/RDS",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "FreeMemoryGB",
        "namespace": "AWS/RDS",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,  # GB → bytes
    },
    {
        "metric": "FreeStorageGB",
        "namespace": "AWS/RDS",
        "metric_name": "FreeStorageSpace",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,
    },
    {
        "metric": "Connections",
        "namespace": "AWS/RDS",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "ReadLatency",
        "namespace": "AWS/RDS",
        "metric_name": "ReadLatency",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WriteLatency",
        "namespace": "AWS/RDS",
        "metric_name": "WriteLatency",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "ConnectionAttempts",
        "namespace": "AWS/RDS",
        "metric_name": "ConnectionAttempts",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_ALB_ALARMS = [
    {
        "metric": "RequestCount",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "RequestCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "ELB5XX",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HTTPCode_ELB_5XX_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "TargetResponseTime",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetResponseTime",
        "dimension_key": "LoadBalancer",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "ELB4XX",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HTTPCode_ELB_4XX_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "TargetConnectionError",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetConnectionErrorCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]

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
    },
    {
        "metric": "TCPClientReset",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Client_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "TCPTargetReset",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Target_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]

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
    },
    {
        "metric": "TGResponseTime",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "TargetResponseTime",
        "dimension_key": "TargetGroup",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]


_AURORA_RDS_ALARMS = [
    {
        "metric": "CPU",
        "namespace": "AWS/RDS",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "FreeMemoryGB",
        "namespace": "AWS/RDS",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
    },
    {
        "metric": "Connections",
        "namespace": "AWS/RDS",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "FreeLocalStorageGB",
        "namespace": "AWS/RDS",
        "metric_name": "FreeLocalStorage",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
    },
    {
        "metric": "ReplicaLag",
        "namespace": "AWS/RDS",
        "metric_name": "AuroraReplicaLagMaximum",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_AURORA_READER_REPLICA_LAG = {
    "metric": "ReaderReplicaLag",
    "namespace": "AWS/RDS",
    "metric_name": "AuroraReplicaLag",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Maximum",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
}

_AURORA_ACU_UTILIZATION = {
    "metric": "ACUUtilization",
    "namespace": "AWS/RDS",
    "metric_name": "ACUUtilization",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Average",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
}

_AURORA_SERVERLESS_CAPACITY = {
    "metric": "ServerlessDatabaseCapacity",
    "namespace": "AWS/RDS",
    "metric_name": "ServerlessDatabaseCapacity",
    "dimension_key": "DBInstanceIdentifier",
    "stat": "Average",
    "comparison": "GreaterThanThreshold",
    "period": 300,
    "evaluation_periods": 1,
}


def _get_aurora_alarm_defs(resource_tags: dict) -> list[dict]:
    """Aurora 인스턴스 변형별 알람 정의 동적 빌드.

    Provisioned: CPU, FreeMemoryGB, Connections, FreeLocalStorageGB + lag
    Serverless v2: CPU, ACUUtilization, Connections + lag
      - FreeMemoryGB 제외: Serverless v2에서 이 메트릭은 "max ACU까지 남은 여유"를 의미하며
        ACUUtilization과 중복됨 (AWS 공식 문서 참조)
      - ServerlessDatabaseCapacity 제외: ACUUtilization이 이미 비율로 커버
    """
    is_serverless = resource_tags.get("_is_serverless_v2") == "true"
    is_writer = resource_tags.get("_is_cluster_writer") == "true"
    has_readers = resource_tags.get("_has_readers") == "true"

    if is_serverless:
        # Serverless v2: CPU + ACUUtilization + Connections (3개)
        alarms = [_AURORA_RDS_ALARMS[0], _AURORA_ACU_UTILIZATION, _AURORA_RDS_ALARMS[2]]
    else:
        # Provisioned: CPU + FreeMemoryGB + Connections + FreeLocalStorageGB
        alarms = list(_AURORA_RDS_ALARMS[:4])

    if is_writer and has_readers:
        alarms.append(_AURORA_RDS_ALARMS[4])  # ReplicaLag
    elif not is_writer:
        alarms.append(_AURORA_READER_REPLICA_LAG)

    return alarms


_DOCDB_ALARMS = [
    {
        "metric": "CPU",
        "namespace": "AWS/DocDB",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "FreeMemoryGB",
        "namespace": "AWS/DocDB",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
    },
    {
        "metric": "Connections",
        "namespace": "AWS/DocDB",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_ELASTICACHE_ALARMS = [
    {
        "metric": "CPU",
        "namespace": "AWS/ElastiCache",
        "metric_name": "CPUUtilization",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "EngineCPU",
        "namespace": "AWS/ElastiCache",
        "metric_name": "EngineCPUUtilization",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SwapUsage",
        "namespace": "AWS/ElastiCache",
        "metric_name": "SwapUsage",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Evictions",
        "namespace": "AWS/ElastiCache",
        "metric_name": "Evictions",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "CurrConnections",
        "namespace": "AWS/ElastiCache",
        "metric_name": "CurrConnections",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

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
    },
]

_LAMBDA_ALARMS = [
    {
        "metric": "Duration",
        "namespace": "AWS/Lambda",
        "metric_name": "Duration",
        "dimension_key": "FunctionName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Errors",
        "namespace": "AWS/Lambda",
        "metric_name": "Errors",
        "dimension_key": "FunctionName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

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

_APIGW_REST_ALARMS = [
    {
        "metric": "ApiLatency",
        "namespace": "AWS/ApiGateway",
        "metric_name": "Latency",
        "dimension_key": "ApiName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api4XXError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "4XXError",
        "dimension_key": "ApiName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api5XXError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "5XXError",
        "dimension_key": "ApiName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_APIGW_HTTP_ALARMS = [
    {
        "metric": "ApiLatency",
        "namespace": "AWS/ApiGateway",
        "metric_name": "Latency",
        "dimension_key": "ApiId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api4xx",
        "namespace": "AWS/ApiGateway",
        "metric_name": "4xx",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "Api5xx",
        "namespace": "AWS/ApiGateway",
        "metric_name": "5xx",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_APIGW_WEBSOCKET_ALARMS = [
    {
        "metric": "WsConnectCount",
        "namespace": "AWS/ApiGateway",
        "metric_name": "ConnectCount",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsMessageCount",
        "namespace": "AWS/ApiGateway",
        "metric_name": "MessageCount",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsIntegrationError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "IntegrationError",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WsExecutionError",
        "namespace": "AWS/ApiGateway",
        "metric_name": "ExecutionError",
        "dimension_key": "ApiId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]


def _get_apigw_alarm_defs(resource_tags: dict) -> list[dict]:
    """APIGW _api_type별 알람 정의 동적 빌드 (Aurora 패턴 준용)."""
    api_type = resource_tags.get("_api_type", "REST")
    if api_type == "HTTP":
        return _APIGW_HTTP_ALARMS
    if api_type == "WEBSOCKET":
        return _APIGW_WEBSOCKET_ALARMS
    return _APIGW_REST_ALARMS


_ACM_ALARMS = [
    {
        "metric": "DaysToExpiry",
        "namespace": "AWS/CertificateManager",
        "metric_name": "DaysToExpiry",
        "dimension_key": "CertificateArn",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
    },
]

_BACKUP_ALARMS = [
    {
        "metric": "BackupJobsFailed",
        "namespace": "AWS/Backup",
        "metric_name": "NumberOfBackupJobsFailed",
        "dimension_key": "BackupVaultName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "BackupJobsAborted",
        "namespace": "AWS/Backup",
        "metric_name": "NumberOfBackupJobsAborted",
        "dimension_key": "BackupVaultName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_MQ_ALARMS = [
    {
        "metric": "MqCPU",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "CpuUtilization",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "HeapUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "HeapUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "JobSchedulerStoreUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "JobSchedulerStorePercentUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "StoreUsage",
        "namespace": "AWS/AmazonMQ",
        "metric_name": "StorePercentUsage",
        "dimension_key": "Broker",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_CLB_ALARMS = [
    {
        "metric": "CLBUnHealthyHost",
        "namespace": "AWS/ELB",
        "metric_name": "UnHealthyHostCount",
        "dimension_key": "LoadBalancerName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLB5XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_ELB_5XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLB4XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_ELB_4XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLBBackend5XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_Backend_5XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "CLBBackend4XX",
        "namespace": "AWS/ELB",
        "metric_name": "HTTPCode_Backend_4XX",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "SurgeQueueLength",
        "namespace": "AWS/ELB",
        "metric_name": "SurgeQueueLength",
        "dimension_key": "LoadBalancerName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
    {
        "metric": "SpilloverCount",
        "namespace": "AWS/ELB",
        "metric_name": "SpilloverCount",
        "dimension_key": "LoadBalancerName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]

_OPENSEARCH_ALARMS = [
    {
        "metric": "ClusterStatusRed",
        "namespace": "AWS/ES",
        "metric_name": "ClusterStatus.red",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "ClusterStatusYellow",
        "namespace": "AWS/ES",
        "metric_name": "ClusterStatus.yellow",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "OSFreeStorageSpace",
        "namespace": "AWS/ES",
        "metric_name": "FreeStorageSpace",
        "dimension_key": "DomainName",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "ClusterIndexWritesBlocked",
        "namespace": "AWS/ES",
        "metric_name": "ClusterIndexWritesBlocked",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "OsCPU",
        "namespace": "AWS/ES",
        "metric_name": "CPUUtilization",
        "dimension_key": "DomainName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "JVMMemoryPressure",
        "namespace": "AWS/ES",
        "metric_name": "JVMMemoryPressure",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "MasterCPU",
        "namespace": "AWS/ES",
        "metric_name": "MasterCPUUtilization",
        "dimension_key": "DomainName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
    {
        "metric": "MasterJVMMemoryPressure",
        "namespace": "AWS/ES",
        "metric_name": "MasterJVMMemoryPressure",
        "dimension_key": "DomainName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "needs_client_id": True,
    },
]

_SQS_ALARMS = [
    {
        "metric": "SQSMessagesVisible",
        "namespace": "AWS/SQS",
        "metric_name": "ApproximateNumberOfMessagesVisible",
        "dimension_key": "QueueName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SQSOldestMessage",
        "namespace": "AWS/SQS",
        "metric_name": "ApproximateAgeOfOldestMessage",
        "dimension_key": "QueueName",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SQSMessagesSent",
        "namespace": "AWS/SQS",
        "metric_name": "NumberOfMessagesSent",
        "dimension_key": "QueueName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_ECS_ALARMS = [
    {
        "metric": "EcsCPU",
        "namespace": "AWS/ECS",
        "metric_name": "CPUUtilization",
        "dimension_key": "ServiceName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "EcsMemory",
        "namespace": "AWS/ECS",
        "metric_name": "MemoryUtilization",
        "dimension_key": "ServiceName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "RunningTaskCount",
        "namespace": "AWS/ECS",
        "metric_name": "RunningTaskCount",
        "dimension_key": "ServiceName",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_MSK_ALARMS = [
    {
        "metric": "OffsetLag",
        "namespace": "AWS/Kafka",
        "metric_name": "SumOffsetLag",
        "dimension_key": "Cluster Name",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "BytesInPerSec",
        "namespace": "AWS/Kafka",
        "metric_name": "BytesInPerSec",
        "dimension_key": "Cluster Name",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "UnderReplicatedPartitions",
        "namespace": "AWS/Kafka",
        "metric_name": "UnderReplicatedPartitions",
        "dimension_key": "Cluster Name",
        "stat": "Maximum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "ActiveControllerCount",
        "namespace": "AWS/Kafka",
        "metric_name": "ActiveControllerCount",
        "dimension_key": "Cluster Name",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]

_DYNAMODB_ALARMS = [
    {
        "metric": "DDBReadCapacity",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ConsumedReadCapacityUnits",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "DDBWriteCapacity",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ConsumedWriteCapacityUnits",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "ThrottledRequests",
        "namespace": "AWS/DynamoDB",
        "metric_name": "ThrottledRequests",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "DDBSystemErrors",
        "namespace": "AWS/DynamoDB",
        "metric_name": "SystemErrors",
        "dimension_key": "TableName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_CLOUDFRONT_ALARMS = [
    {
        "metric": "CF5xxErrorRate",
        "namespace": "AWS/CloudFront",
        "metric_name": "5xxErrorRate",
        "dimension_key": "DistributionId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CF4xxErrorRate",
        "namespace": "AWS/CloudFront",
        "metric_name": "4xxErrorRate",
        "dimension_key": "DistributionId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CFRequests",
        "namespace": "AWS/CloudFront",
        "metric_name": "Requests",
        "dimension_key": "DistributionId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
    {
        "metric": "CFBytesDownloaded",
        "namespace": "AWS/CloudFront",
        "metric_name": "BytesDownloaded",
        "dimension_key": "DistributionId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "region": "us-east-1",
    },
]

_WAF_ALARMS = [
    {
        "metric": "WAFBlockedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "BlockedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WAFAllowedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "AllowedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "WAFCountedRequests",
        "namespace": "AWS/WAFV2",
        "metric_name": "CountedRequests",
        "dimension_key": "WebACL",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_ROUTE53_ALARMS = [
    {
        "metric": "HealthCheckStatus",
        "namespace": "AWS/Route53",
        "metric_name": "HealthCheckStatus",
        "dimension_key": "HealthCheckId",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
        "region": "us-east-1",
    },
]

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

_EFS_ALARMS = [
    {
        "metric": "BurstCreditBalance",
        "namespace": "AWS/EFS",
        "metric_name": "BurstCreditBalance",
        "dimension_key": "FileSystemId",
        "stat": "Minimum",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "PercentIOLimit",
        "namespace": "AWS/EFS",
        "metric_name": "PercentIOLimit",
        "dimension_key": "FileSystemId",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "EFSClientConnections",
        "namespace": "AWS/EFS",
        "metric_name": "ClientConnections",
        "dimension_key": "FileSystemId",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_S3_ALARMS = [
    {
        "metric": "S34xxErrors",
        "namespace": "AWS/S3",
        "metric_name": "4xxErrors",
        "dimension_key": "BucketName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "S35xxErrors",
        "namespace": "AWS/S3",
        "metric_name": "5xxErrors",
        "dimension_key": "BucketName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "S3BucketSizeBytes",
        "namespace": "AWS/S3",
        "metric_name": "BucketSizeBytes",
        "dimension_key": "BucketName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
        "needs_storage_type": True,
    },
    {
        "metric": "S3NumberOfObjects",
        "namespace": "AWS/S3",
        "metric_name": "NumberOfObjects",
        "dimension_key": "BucketName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 86400,
        "evaluation_periods": 1,
        "needs_storage_type": True,
    },
]

_SAGEMAKER_ALARMS = [
    {
        "metric": "SMInvocations",
        "namespace": "AWS/SageMaker",
        "metric_name": "Invocations",
        "dimension_key": "EndpointName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMInvocationErrors",
        "namespace": "AWS/SageMaker",
        "metric_name": "InvocationErrors",
        "dimension_key": "EndpointName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMModelLatency",
        "namespace": "AWS/SageMaker",
        "metric_name": "ModelLatency",
        "dimension_key": "EndpointName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SMCPU",
        "namespace": "AWS/SageMaker",
        "metric_name": "CPUUtilization",
        "dimension_key": "EndpointName",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_SNS_ALARMS = [
    {
        "metric": "SNSNotificationsFailed",
        "namespace": "AWS/SNS",
        "metric_name": "NumberOfNotificationsFailed",
        "dimension_key": "TopicName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
    {
        "metric": "SNSMessagesPublished",
        "namespace": "AWS/SNS",
        "metric_name": "NumberOfMessagesPublished",
        "dimension_key": "TopicName",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
    },
]

_NLB_TG_EXCLUDED_METRICS = {"RequestCountPerTarget", "TGResponseTime"}


def _get_alarm_defs(resource_type: str, resource_tags: dict | None = None) -> list[dict]:
    if resource_type == "EC2":
        return _EC2_ALARMS
    elif resource_type == "RDS":
        return _RDS_ALARMS
    elif resource_type == "AuroraRDS":
        return _get_aurora_alarm_defs(resource_tags or {})
    elif resource_type == "ALB":
        return _ALB_ALARMS
    elif resource_type == "NLB":
        return _NLB_ALARMS
    elif resource_type == "DocDB":
        return _DOCDB_ALARMS
    elif resource_type == "ElastiCache":
        return _ELASTICACHE_ALARMS
    elif resource_type == "NAT":
        return _NATGW_ALARMS
    elif resource_type == "TG":
        # TargetType=alb인 TG는 HealthyHostCount/UnHealthyHostCount 메트릭이
        # CloudWatch에서 발행되지 않음 (AWS 제약사항) → 알람 생성 스킵
        if resource_tags is not None and resource_tags.get("_target_type") == "alb":
            return []
        if resource_tags is not None and resource_tags.get("_lb_type") == "network":
            return [d for d in _TG_ALARMS if d["metric"] not in _NLB_TG_EXCLUDED_METRICS]
        return _TG_ALARMS
    elif resource_type == "Lambda":
        return _LAMBDA_ALARMS
    elif resource_type == "VPN":
        return _VPN_ALARMS
    elif resource_type == "APIGW":
        return _get_apigw_alarm_defs(resource_tags or {})
    elif resource_type == "ACM":
        return _ACM_ALARMS
    elif resource_type == "Backup":
        return _BACKUP_ALARMS
    elif resource_type == "MQ":
        return _MQ_ALARMS
    elif resource_type == "CLB":
        return _CLB_ALARMS
    elif resource_type == "OpenSearch":
        return _OPENSEARCH_ALARMS
    elif resource_type == "SQS":
        return _SQS_ALARMS
    elif resource_type == "ECS":
        return _ECS_ALARMS
    elif resource_type == "MSK":
        return _MSK_ALARMS
    elif resource_type == "DynamoDB":
        return _DYNAMODB_ALARMS
    elif resource_type == "CloudFront":
        return _CLOUDFRONT_ALARMS
    elif resource_type == "WAF":
        return _WAF_ALARMS
    elif resource_type == "Route53":
        return _ROUTE53_ALARMS
    elif resource_type == "DX":
        return _DX_ALARMS
    elif resource_type == "EFS":
        return _EFS_ALARMS
    elif resource_type == "S3":
        return _S3_ALARMS
    elif resource_type == "SageMaker":
        return _SAGEMAKER_ALARMS
    elif resource_type == "SNS":
        return _SNS_ALARMS
    return []


# resource_type별 하드코딩 메트릭 키
_HARDCODED_METRIC_KEYS: dict[str, set[str]] = {
    "EC2": {"CPU", "Memory", "Disk", "StatusCheckFailed"},
    "RDS": {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency", "ConnectionAttempts"},
    "ALB": {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"},
    "NLB": {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"},
    "TG": {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"},
    "AuroraRDS": {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag", "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity"},
    "DocDB": {"CPU", "FreeMemoryGB", "Connections"},
    "ElastiCache": {"CPU", "EngineCPU", "SwapUsage", "Evictions", "CurrConnections"},
    "NAT": {"PacketsDropCount", "ErrorPortAllocation"},
    "Lambda": {"Duration", "Errors"},
    "VPN": {"TunnelState"},
    "APIGW": {
        "ApiLatency", "Api4XXError", "Api5XXError",
        "Api4xx", "Api5xx",
        "WsConnectCount", "WsMessageCount",
        "WsIntegrationError", "WsExecutionError",
    },
    "ACM": {"DaysToExpiry"},
    "Backup": {"BackupJobsFailed", "BackupJobsAborted"},
    "MQ": {"MqCPU", "HeapUsage", "JobSchedulerStoreUsage", "StoreUsage"},
    "CLB": {
        "CLBUnHealthyHost", "CLB5XX", "CLB4XX",
        "CLBBackend5XX", "CLBBackend4XX",
        "SurgeQueueLength", "SpilloverCount",
    },
    "OpenSearch": {
        "ClusterStatusRed", "ClusterStatusYellow",
        "OSFreeStorageSpace", "ClusterIndexWritesBlocked",
        "OsCPU", "JVMMemoryPressure",
        "MasterCPU", "MasterJVMMemoryPressure",
    },
    "SQS": {"SQSMessagesVisible", "SQSOldestMessage", "SQSMessagesSent"},
    "ECS": {"EcsCPU", "EcsMemory", "RunningTaskCount"},
    "MSK": {"OffsetLag", "BytesInPerSec", "UnderReplicatedPartitions", "ActiveControllerCount"},
    "DynamoDB": {"DDBReadCapacity", "DDBWriteCapacity", "ThrottledRequests", "DDBSystemErrors"},
    "CloudFront": {"CF5xxErrorRate", "CF4xxErrorRate", "CFRequests", "CFBytesDownloaded"},
    "WAF": {"WAFBlockedRequests", "WAFAllowedRequests", "WAFCountedRequests"},
    "Route53": {"HealthCheckStatus"},
    "DX": {"ConnectionState"},
    "EFS": {"BurstCreditBalance", "PercentIOLimit", "EFSClientConnections"},
    "S3": {"S34xxErrors", "S35xxErrors", "S3BucketSizeBytes", "S3NumberOfObjects"},
    "SageMaker": {"SMInvocations", "SMInvocationErrors", "SMModelLatency", "SMCPU"},
    "SNS": {"SNSNotificationsFailed", "SNSMessagesPublished"},
}

# resource_type별 CloudWatch 네임스페이스 목록
_NAMESPACE_MAP: dict[str, list[str]] = {
    "EC2": ["AWS/EC2", "CWAgent"],
    "RDS": ["AWS/RDS"],
    "ALB": ["AWS/ApplicationELB"],
    "NLB": ["AWS/NetworkELB"],
    "TG": ["AWS/ApplicationELB", "AWS/NetworkELB"],
    "AuroraRDS": ["AWS/RDS"],
    "DocDB": ["AWS/DocDB"],
    "ElastiCache": ["AWS/ElastiCache"],
    "NAT": ["AWS/NATGateway"],
    "Lambda": ["AWS/Lambda"],
    "VPN": ["AWS/VPN"],
    "APIGW": ["AWS/ApiGateway"],
    "ACM": ["AWS/CertificateManager"],
    "Backup": ["AWS/Backup"],
    "MQ": ["AWS/AmazonMQ"],
    "CLB": ["AWS/ELB"],
    "OpenSearch": ["AWS/ES"],
    "SQS": ["AWS/SQS"],
    "ECS": ["AWS/ECS"],
    "MSK": ["AWS/Kafka"],
    "DynamoDB": ["AWS/DynamoDB"],
    "CloudFront": ["AWS/CloudFront"],
    "WAF": ["AWS/WAFV2"],
    "Route53": ["AWS/Route53"],
    "DX": ["AWS/DX"],
    "EFS": ["AWS/EFS"],
    "S3": ["AWS/S3"],
    "SageMaker": ["AWS/SageMaker"],
    "SNS": ["AWS/SNS"],
}

# resource_type별 디멘션 키
_DIMENSION_KEY_MAP: dict[str, str] = {
    "EC2": "InstanceId",
    "RDS": "DBInstanceIdentifier",
    "ALB": "LoadBalancer",
    "NLB": "LoadBalancer",
    "TG": "TargetGroup",
    "AuroraRDS": "DBInstanceIdentifier",
    "DocDB": "DBInstanceIdentifier",
    "ElastiCache": "CacheClusterId",
    "NAT": "NatGatewayId",
    "Lambda": "FunctionName",
    "VPN": "VpnId",
    "APIGW": "ApiName",
    "ACM": "CertificateArn",
    "Backup": "BackupVaultName",
    "MQ": "Broker",
    "CLB": "LoadBalancerName",
    "OpenSearch": "DomainName",
    "SQS": "QueueName",
    "ECS": "ServiceName",
    "MSK": "Cluster Name",
    "DynamoDB": "TableName",
    "CloudFront": "DistributionId",
    "WAF": "WebACL",
    "Route53": "HealthCheckId",
    "DX": "ConnectionId",
    "EFS": "FileSystemId",
    "S3": "BucketName",
    "SageMaker": "EndpointName",
    "SNS": "TopicName",
}


def _get_hardcoded_metric_keys(resource_type: str, resource_tags: dict | None = None) -> set[str]:
    """resource_type과 resource_tags 기반으로 하드코딩 메트릭 키 집합을 반환.

    _get_alarm_defs() 결과에서 동적으로 추출하여 NLB TG 등 LB 타입별 차이를 반영한다.
    """
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    return {d["metric"] for d in alarm_defs}


def _metric_name_to_key(metric_name: str) -> str:
    """CloudWatch 메트릭 이름을 내부 메트릭 키로 변환.

    CPUUtilization → CPU, mem_used_percent → Memory, disk_used_percent → Disk
    """
    mapping = {
        "CPUUtilization": "CPU",
        "mem_used_percent": "Memory",
        "disk_used_percent": "Disk",
        "FreeableMemory": "FreeMemoryGB",
        "FreeStorageSpace": "FreeStorageGB",
        "DatabaseConnections": "Connections",
        "RequestCount": "RequestCount",
        "HealthyHostCount": "HealthyHostCount",
        "UnHealthyHostCount": "UnHealthyHostCount",
        "ProcessedBytes": "ProcessedBytes",
        "ActiveFlowCount": "ActiveFlowCount",
        "NewFlowCount": "NewFlowCount",
        "StatusCheckFailed": "StatusCheckFailed",
        "ReadLatency": "ReadLatency",
        "WriteLatency": "WriteLatency",
        "HTTPCode_ELB_5XX_Count": "ELB5XX",
        "HTTPCode_ELB_4XX_Count": "ELB4XX",
        "TargetConnectionErrorCount": "TargetConnectionError",
        "TargetResponseTime": "TargetResponseTime",
        "TCP_Client_Reset_Count": "TCPClientReset",
        "TCP_Target_Reset_Count": "TCPTargetReset",
        "RequestCountPerTarget": "RequestCountPerTarget",
        "FreeLocalStorage": "FreeLocalStorageGB",
        "AuroraReplicaLagMaximum": "ReplicaLag",
        "AuroraReplicaLag": "ReaderReplicaLag",
        "ACUUtilization": "ACUUtilization",
        "ServerlessDatabaseCapacity": "ServerlessDatabaseCapacity",
        "ConnectionAttempts": "ConnectionAttempts",
        "EngineCPUUtilization": "EngineCPU",
        "SwapUsage": "SwapUsage",
        "Evictions": "Evictions",
        "CurrConnections": "CurrConnections",
        "PacketsDropCount": "PacketsDropCount",
        "ErrorPortAllocation": "ErrorPortAllocation",
        "Duration": "Duration",
        "Errors": "Errors",
        "TunnelState": "TunnelState",
        "Latency": "ApiLatency",
        "4XXError": "Api4XXError",
        "5XXError": "Api5XXError",
        "4xx": "Api4xx",
        "5xx": "Api5xx",
        "ConnectCount": "WsConnectCount",
        "MessageCount": "WsMessageCount",
        "IntegrationError": "WsIntegrationError",
        "ExecutionError": "WsExecutionError",
        "DaysToExpiry": "DaysToExpiry",
        "NumberOfBackupJobsFailed": "BackupJobsFailed",
        "NumberOfBackupJobsAborted": "BackupJobsAborted",
        "CpuUtilization": "MqCPU",
        "HeapUsage": "HeapUsage",
        "JobSchedulerStorePercentUsage": "JobSchedulerStoreUsage",
        "StorePercentUsage": "StoreUsage",
        "UnHealthyHostCount": "CLBUnHealthyHost",
        "HTTPCode_ELB_5XX": "CLB5XX",
        "HTTPCode_ELB_4XX": "CLB4XX",
        "HTTPCode_Backend_5XX": "CLBBackend5XX",
        "HTTPCode_Backend_4XX": "CLBBackend4XX",
        "SurgeQueueLength": "SurgeQueueLength",
        "SpilloverCount": "SpilloverCount",
        "ClusterStatus.red": "ClusterStatusRed",
        "ClusterStatus.yellow": "ClusterStatusYellow",
        "ClusterIndexWritesBlocked": "ClusterIndexWritesBlocked",
        "MasterCPUUtilization": "MasterCPU",
        "MasterJVMMemoryPressure": "MasterJVMMemoryPressure",
        "ApproximateNumberOfMessagesVisible": "SQSMessagesVisible",
        "ApproximateAgeOfOldestMessage": "SQSOldestMessage",
        "NumberOfMessagesSent": "SQSMessagesSent",
        "MemoryUtilization": "EcsMemory",
        "RunningTaskCount": "RunningTaskCount",
        "SumOffsetLag": "OffsetLag",
        "BytesInPerSec": "BytesInPerSec",
        "UnderReplicatedPartitions": "UnderReplicatedPartitions",
        "ActiveControllerCount": "ActiveControllerCount",
        "ConsumedReadCapacityUnits": "DDBReadCapacity",
        "ConsumedWriteCapacityUnits": "DDBWriteCapacity",
        "ThrottledRequests": "ThrottledRequests",
        "SystemErrors": "DDBSystemErrors",
        "5xxErrorRate": "CF5xxErrorRate",
        "4xxErrorRate": "CF4xxErrorRate",
        "Requests": "CFRequests",
        "BytesDownloaded": "CFBytesDownloaded",
        "BlockedRequests": "WAFBlockedRequests",
        "AllowedRequests": "WAFAllowedRequests",
        "CountedRequests": "WAFCountedRequests",
        "HealthCheckStatus": "HealthCheckStatus",
        "ConnectionState": "ConnectionState",
        "BurstCreditBalance": "BurstCreditBalance",
        "PercentIOLimit": "PercentIOLimit",
        "ClientConnections": "EFSClientConnections",
        "4xxErrors": "S34xxErrors",
        "5xxErrors": "S35xxErrors",
        "BucketSizeBytes": "S3BucketSizeBytes",
        "NumberOfObjects": "S3NumberOfObjects",
        "Invocations": "SMInvocations",
        "InvocationErrors": "SMInvocationErrors",
        "ModelLatency": "SMModelLatency",
        "NumberOfNotificationsFailed": "SNSNotificationsFailed",
        "NumberOfMessagesPublished": "SNSMessagesPublished",
    }
    return mapping.get(metric_name, metric_name)
