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
    # Friendly keys (canonical — used in alarm descriptions and tag lookups)
    "CPU": ("CPUUtilization", ">", "%"),
    "Memory": ("mem_used_percent", ">", "%"),
    "FreeMemoryGB": ("FreeableMemory", "<", "GB"),
    "FreeStorageGB": ("FreeStorageSpace", "<", "GB"),
    "Connections": ("DatabaseConnections", ">", ""),
    "ELB5XX": ("HTTPCode_ELB_5XX_Count", ">", ""),
    "TCPClientReset": ("TCP_Client_Reset_Count", ">", ""),
    "TCPTargetReset": ("TCP_Target_Reset_Count", ">", ""),
    "TGResponseTime": ("TargetResponseTime", ">", "s"),
    # CW-name keyed entries (kept for backward compat with pre-existing alarms)
    "CPUUtilization": ("CPUUtilization", ">", "%"),
    "mem_used_percent": ("mem_used_percent", ">", "%"),
    "disk_used_percent": ("disk_used_percent", ">", "%"),
    "FreeableMemory": ("FreeableMemory", "<", "GB"),
    "FreeStorageSpace": ("FreeStorageSpace", "<", "GB"),
    "DatabaseConnections": ("DatabaseConnections", ">", ""),
    "RequestCount": ("RequestCount", ">", ""),
    "HealthyHostCount": ("HealthyHostCount", "<", ""),
    "UnHealthyHostCount": ("UnHealthyHostCount", ">", ""),
    "ProcessedBytes": ("ProcessedBytes", ">", ""),
    "ActiveFlowCount": ("ActiveFlowCount", ">", ""),
    "NewFlowCount": ("NewFlowCount", ">", ""),
    "StatusCheckFailed": ("StatusCheckFailed", ">", ""),
    "StatusCheckFailed_Application": ("StatusCheckFailed_Application", ">", ""),
    "ReadLatency": ("ReadLatency", ">", "s"),
    "WriteLatency": ("WriteLatency", ">", "s"),
    "HTTPCode_ELB_5XX_Count": ("HTTPCode_ELB_5XX_Count", ">", ""),
    "ELB4XX": ("HTTPCode_ELB_4XX_Count", ">", ""),
    "TargetConnectionError": ("TargetConnectionErrorCount", ">", ""),
    "TargetResponseTime": ("TargetResponseTime", ">", "s"),
    "TCP_Client_Reset_Count": ("TCP_Client_Reset_Count", ">", ""),
    "TCP_Target_Reset_Count": ("TCP_Target_Reset_Count", ">", ""),
    "RequestCountPerTarget": ("RequestCountPerTarget", ">", ""),
    "FreeLocalStorageGB": ("FreeLocalStorage", "<", "GB"),
    "FreeLocalStorage": ("FreeLocalStorage", "<", "GB"),
    "ReplicaLag": ("AuroraReplicaLagMaximum", ">", "μs"),
    "ReaderReplicaLag": ("AuroraReplicaLag", ">", "μs"),
    "ACUUtilization": ("ACUUtilization", ">", "%"),
    "ServerlessDatabaseCapacity": ("ServerlessDatabaseCapacity", ">", "ACU"),
    "ConnectionAttempts": ("ConnectionAttempts", ">", ""),
    "EngineCPU": ("EngineCPUUtilization", ">=", "%"),
    "DatabaseMemoryUsagePercentage": ("DatabaseMemoryUsagePercentage", ">=", "%"),
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
#: EC2 애플리케이션 상태 검사(2026-08 출시)의 인스턴스 단위 집계 지표.
#: AWS가 VPC 내 관리형 ENI로 앱의 HTTP 엔드포인트를 60초마다 찔러 보고 0/1로 발행한다.
APP_STATUS_METRIC_KEY = "StatusCheckFailed_Application"

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


_RDS_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/RDS",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeableMemory",
        "namespace": "AWS/RDS",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,  # GB → bytes
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeStorageSpace",
        "namespace": "AWS/RDS",
        "metric_name": "FreeStorageSpace",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1024 * 1024 * 1024,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseConnections",
        "namespace": "AWS/RDS",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "notBreaching",  # 쿼리 없으면 데이터 없음
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
        "treat_missing_data": "notBreaching",  # 쿼리 없으면 데이터 없음
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
        "treat_missing_data": "notBreaching",  # 연결 시도 없으면 데이터 없음
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
        "treat_missing_data": "notBreaching",  # 트래픽 없으면 데이터 없음
    },
    {
        "metric": "HTTPCode_ELB_5XX_Count",
        "namespace": "AWS/ApplicationELB",
        "metric_name": "HTTPCode_ELB_5XX_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",  # 요청 없으면 에러도 없음
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
        "treat_missing_data": "notBreaching",  # 요청 없으면 응답 시간 없음
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
        "treat_missing_data": "notBreaching",
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
        "treat_missing_data": "notBreaching",
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
        "treat_missing_data": "notBreaching",  # 트래픽 없으면 데이터 없음
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
        "treat_missing_data": "notBreaching",  # 활성 연결 없으면 데이터 없음
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
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "TCP_Client_Reset_Count",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Client_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
    },
    {
        "metric": "TCP_Target_Reset_Count",
        "namespace": "AWS/NetworkELB",
        "metric_name": "TCP_Target_Reset_Count",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
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


_AURORA_RDS_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/RDS",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeableMemory",
        "namespace": "AWS/RDS",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseConnections",
        "namespace": "AWS/RDS",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeLocalStorage",
        "namespace": "AWS/RDS",
        "metric_name": "FreeLocalStorage",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "missing",
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
    "treat_missing_data": "missing",
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
    "treat_missing_data": "breaching",  # Serverless v2 실행 중이면 항상 발행
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
        "metric": "CPUUtilization",
        "namespace": "AWS/DocDB",
        "metric_name": "CPUUtilization",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "FreeableMemory",
        "namespace": "AWS/DocDB",
        "metric_name": "FreeableMemory",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "transform_threshold": lambda gb: gb * 1073741824,
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseConnections",
        "namespace": "AWS/DocDB",
        "metric_name": "DatabaseConnections",
        "dimension_key": "DBInstanceIdentifier",
        "stat": "Average",
        "comparison": "GreaterThanThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
    },
]

_ELASTICACHE_ALARMS = [
    {
        "metric": "CPUUtilization",
        "namespace": "AWS/ElastiCache",
        "metric_name": "CPUUtilization",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
    },
    {
        "metric": "DatabaseMemoryUsagePercentage",
        "namespace": "AWS/ElastiCache",
        "metric_name": "DatabaseMemoryUsagePercentage",
        "dimension_key": "CacheClusterId",
        "stat": "Average",
        "comparison": "GreaterThanOrEqualToThreshold",
        "period": 300,
        "evaluation_periods": 1,
        "treat_missing_data": "notBreaching",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "missing",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "breaching",
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
        "region": "us-east-1",
        "treat_missing_data": "breaching",
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
        "treat_missing_data": "missing",  # 일간 메트릭, 중간 기간 missing은 정상 → 상태 유지
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
        "treat_missing_data": "missing",  # 일간 메트릭, 중간 기간 missing은 정상 → 상태 유지
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

_NLB_TG_EXCLUDED_METRICS = {"RequestCountPerTarget", "TargetResponseTime"}


# ──────────────────────────────────────────────
# M-of-N 평가 정책 (Severity 기반)
# ──────────────────────────────────────────────
# 데이터포인트 1개 초과로 즉시 울리는 오탐(순간 스파이크)을 줄이기 위해,
# 심각도에 따라 "N개 평가 창에서 M개 초과 시 알람"을 기본 적용한다.
# 값: (evaluation_periods, datapoints_to_alarm)
_EVAL_POLICY_BY_SEVERITY: dict[str, tuple[int, int]] = {
    "SEV-2": (3, 2),   # 에러 급증: 15분 창에서 10분 이상 지속 시
    "SEV-3": (3, 2),   # 포화도: CPU/메모리는 지속성이 판단 기준
    "SEV-4": (5, 3),   # 성능 저하: 추세로 판단
    "SEV-5": (5, 3),   # 참고 지표
}


def _apply_eval_policy(defs: list[dict]) -> list[dict]:
    """Severity 기반 M-of-N 평가 정책을 알람 정의에 적용한다.

    적용 제외 (즉시 평가 1/1 유지):
    - SEV-1: 가용성 직결 — 감지 지연 불가
    - treat_missing_data="breaching": 데이터 없음=장애로 보는 메트릭.
      M-of-N을 얹으면 다운 감지 자체가 M배 늦어진다.
    - period ≥ 1시간: 저빈도 메트릭(DaysToExpiry 등)은 스파이크 필터가
      무의미하고 알림만 하루 단위로 늦어진다.
    - 정의가 datapoints_to_alarm을 직접 명시: 개별 오버라이드 존중.

    원본 정의 dict는 변경하지 않는다(적용 시 복사본 반환).
    """
    out = []
    for d in defs:
        severity = get_severity(d.get("metric_key") or d["metric"])
        policy = _EVAL_POLICY_BY_SEVERITY.get(severity)
        if (
            policy is None
            or d.get("treat_missing_data") == "breaching"
            or d.get("period", 0) >= 3600
            or "datapoints_to_alarm" in d
        ):
            out.append(d)
            continue
        ep, dp = policy
        out.append({**d, "evaluation_periods": ep, "datapoints_to_alarm": dp})
    return out


def get_dynamic_eval_policy(metric_name: str) -> tuple[int, int]:
    """동적(Threshold_* 태그) 알람의 평가 정책.

    동적 알람은 treat_missing_data=notBreaching·period=300 고정이므로
    Severity 가드만 적용한다. SEV-1 메트릭은 정책 표에 없어 즉시(1/1) 평가.
    """
    return _EVAL_POLICY_BY_SEVERITY.get(get_severity(metric_name), (1, 1))


def _get_alarm_defs(resource_type: str, resource_tags: dict | None = None) -> list[dict]:
    """리소스 타입의 알람 정의 (M-of-N 평가 정책 적용 후)."""
    return _apply_eval_policy(_get_alarm_defs_raw(resource_type, resource_tags))


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


#: 타입 → 알람 정의. 값은 리스트(고정) 또는 `Callable[[resource_tags], list]`(태그 조건부).
#: **이 표의 키가 곧 "알람을 가진 리소스 타입" 목록이다** — 아래 파생 뷰들이 전부 여기서 나온다.
#: (docs/specs/resource-type-registry — P2에서 타입별 스펙 객체로 옮긴다.)
_ALARM_DEFS_BY_TYPE: dict = {
    "EC2": _get_ec2_alarm_defs,
    "RDS": _RDS_ALARMS,
    "ALB": _ALB_ALARMS,
    "NLB": _NLB_ALARMS,
    "TG": _get_tg_alarm_defs,
    "AuroraRDS": _get_aurora_alarm_defs,
    "DocDB": _DOCDB_ALARMS,
    "ElastiCache": _ELASTICACHE_ALARMS,
    "NAT": _NATGW_ALARMS,
    "Lambda": _LAMBDA_ALARMS,
    "VPN": _VPN_ALARMS,
    "APIGW": _get_apigw_alarm_defs,
    "ACM": _ACM_ALARMS,
    "Backup": _BACKUP_ALARMS,
    "MQ": _MQ_ALARMS,
    "CLB": _CLB_ALARMS,
    "OpenSearch": _OPENSEARCH_ALARMS,
    "SQS": _SQS_ALARMS,
    "ECS": _ECS_ALARMS,
    "MSK": _MSK_ALARMS,
    "DynamoDB": _DYNAMODB_ALARMS,
    "CloudFront": _CLOUDFRONT_ALARMS,
    "WAF": _WAF_ALARMS,
    "Route53": _ROUTE53_ALARMS,
    "DX": _DX_ALARMS,
    "EFS": _EFS_ALARMS,
    "S3": _S3_ALARMS,
    "SageMaker": _SAGEMAKER_ALARMS,
    "SNS": _SNS_ALARMS,
}


def _get_alarm_defs_raw(resource_type: str, resource_tags: dict | None = None) -> list[dict]:
    entry = _ALARM_DEFS_BY_TYPE.get(resource_type)
    if entry is None:
        return []
    return entry(resource_tags or {}) if callable(entry) else entry


# ──────────────────────────────────────────────
# 타입별 파생 뷰 — 손으로 적지 않고 알람 정의에서 계산한다 (docs/specs/resource-type-registry P1)
# ──────────────────────────────────────────────
# 아래 세 표는 2026-09까지 손으로 유지됐고, 정의와 어긋나지 않는지를 PBT가 지켰다. 정의에서 파생되는
# 값을 두 번 적을 이유가 없다 — 이제 정의가 바뀌면 표가 따라온다. 테스트가 지키는 것은 "파생 규칙이
# 조건 분기의 변형을 전부 열거하는가"다(tests/test_pbt_registry_completeness.py). 규칙은 셋이 다르다:
#   메트릭 키   = 모든 변형의 합집합 − 옵트인(`opt_in`)      (정적 표라 태그 조건부 키도 담는다)
#   네임스페이스 = 모든 변형의 합집합 + 빌드 시 해석기가 바꿔 끼우는 것(_EXTRA_NAMESPACES)
#   디멘션 키   = **기본 변형**(태그 없음)의 키                (변형은 다를 수 있다 — APIGW HTTP/WS는 ApiId)

#: 조건부 정의 함수가 읽는 태그의 **모든 조합**. 파생은 이 변형을 전부 열거해 합친다.
#: 조건 분기에서 태그를 새로 읽으면 여기에도 적어야 한다 — 완전성 테스트가 함수 소스를 훑어 잡는다.
_ALARM_DEF_VARIANTS: dict[str, tuple[dict, ...]] = {
    "EC2": ({}, {f"Threshold_{APP_STATUS_METRIC_KEY}": "1"}),
    "AuroraRDS": tuple(
        {"_is_serverless_v2": s, "_is_cluster_writer": w, "_has_readers": r}
        for s in ("true", "false") for w in ("true", "false") for r in ("true", "false")
    ),
    "TG": ({}, {"_lb_type": "network"}, {"_target_type": "alb"}),
    "APIGW": tuple({"_api_type": t} for t in ("REST", "HTTP", "WEBSOCKET")),
}

#: 정의에는 없지만 빌드 시 해석기가 태그를 보고 바꿔 끼우는 네임스페이스
#: (`dimension_builder._resolve_tg_namespace`). 정의가 그 지식을 갖게 되면(P2, TG 스펙) 사라진다.
_EXTRA_NAMESPACES: dict[str, tuple[str, ...]] = {"TG": ("AWS/NetworkELB",)}


def _variant_defs(resource_type: str) -> list[dict]:
    """모든 변형의 알람 정의 — 중복 제거, 등장 순서 유지."""
    out: list[dict] = []
    seen: set[int] = set()
    for tags in _ALARM_DEF_VARIANTS.get(resource_type, ({},)):
        for d in _get_alarm_defs_raw(resource_type, tags):
            if id(d) not in seen:
                seen.add(id(d))
                out.append(d)
    return out


def _derive_metric_keys() -> dict[str, set[str]]:
    """타입별 기본 알람의 메트릭 키(tag_key = Threshold_{key}). 옵트인 정의는 뺀다 — 태그가 있어야 붙는
    알람이고, 동적 알람과의 중복은 `_get_hardcoded_metric_keys()`가 태그를 함께 보며 막는다."""
    return {
        t: {d.get("metric_key") or d["metric"] for d in _variant_defs(t) if not d.get("opt_in")}
        for t in _ALARM_DEFS_BY_TYPE
    }


def _derive_namespaces() -> dict[str, list[str]]:
    """타입별 CloudWatch 네임스페이스(메트릭 탐색 순서 = 정의 등장 순서)."""
    out: dict[str, list[str]] = {}
    for t in _ALARM_DEFS_BY_TYPE:
        ns: list[str] = []
        for d in _variant_defs(t):
            if d["namespace"] not in ns:
                ns.append(d["namespace"])
        for extra in _EXTRA_NAMESPACES.get(t, ()):
            if extra not in ns:
                ns.append(extra)
        out[t] = ns
    return out


def _derive_dimension_keys() -> dict[str, str]:
    """타입별 디멘션 키 — 기본 변형 정의들이 공유하는 키. 타입 수준 탐색(`dimension_builder`,
    `routes/resources.py`)이 쓰는 기본값이고, 알람 생성은 정의의 키를 직접 쓴다."""
    out: dict[str, str] = {}
    for t in _ALARM_DEFS_BY_TYPE:
        keys = list(dict.fromkeys(d["dimension_key"] for d in _get_alarm_defs_raw(t, {})))
        if len(keys) != 1:
            raise RuntimeError(f"{t}: default alarm defs must share one dimension_key, got {keys}")
        out[t] = keys[0]
    return out


_HARDCODED_METRIC_KEYS: dict[str, set[str]] = _derive_metric_keys()
_NAMESPACE_MAP: dict[str, list[str]] = _derive_namespaces()
_DIMENSION_KEY_MAP: dict[str, str] = _derive_dimension_keys()

# 글로벌 서비스 리전 매핑: 메트릭이 us-east-1에서만 발행되는 리소스 타입
# 알람 생성/검색/삭제 시 해당 리전의 CloudWatch 클라이언트를 사용해야 한다.
_GLOBAL_SERVICE_REGION: dict[str, str] = {
    "CloudFront": "us-east-1",
    "Route53": "us-east-1",
}


def _get_hardcoded_metric_keys(resource_type: str, resource_tags: dict | None = None) -> set[str]:
    """resource_type과 resource_tags 기반으로 하드코딩 메트릭 키 집합을 반환.

    metric_key 우선, 없으면 metric 사용. NLB TG 등 LB 타입별 차이를 반영한다.
    반환값은 Threshold_{key} 태그 suffix와 일치한다.
    """
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    return {d.get("metric_key") or d["metric"] for d in alarm_defs}


# _METRIC_DISPLAY의 display_name → metric_key 역방향 조회 캐시
_METRIC_NAME_TO_KEY: dict[str, str] = {
    display_name: key
    for key, (display_name, _, _) in _METRIC_DISPLAY.items()
    if display_name != key  # 동일한 경우 직접 키 조회로 처리
}


def _metric_name_to_key(cw_name: str) -> str:
    """CloudWatch 메트릭 이름 → 내부 메트릭 키 변환.

    1. 직접 키 매칭 (cw_name이 이미 metric_key인 경우)
    2. display_name 역방향 조회 (_METRIC_DISPLAY[key][0] == cw_name)
    3. 매칭 실패 시 cw_name 그대로 반환
    """
    if cw_name in _METRIC_DISPLAY:
        return cw_name
    return _METRIC_NAME_TO_KEY.get(cw_name, cw_name)


# ──────────────────────────────────────────────
# Severity 등급 체계 (Phase2 §13, PagerDuty SEV 기준)
# ──────────────────────────────────────────────

# 메트릭 키 → 기본 Severity 매핑.
# 기준: 해당 메트릭이 ALARM 상태일 때의 비즈니스 영향도.
# 미정의 메트릭은 get_severity()에서 "SEV-5"로 폴백.
_DEFAULT_SEVERITY: dict[str, str] = {
    # SEV-1: 서비스 완전 중단 또는 접근 불가
    "StatusCheckFailed":  "SEV-1",
    "StatusCheckFailed_Application": "SEV-1",   # 앱이 응답하지 않음 — 시스템 검사와 같은 급
    "HealthyHostCount":   "SEV-1",
    "TunnelState":        "SEV-1",
    "ConnectionState":    "SEV-1",
    "HealthCheckStatus":  "SEV-1",
    "ActiveControllerCount": "SEV-1",
    # docs/ALARM-RULES.md §13-2에 SEV-1로 정의되어 있으나 코드에 누락돼
    # SEV-5로 폴백되던 항목 (클러스터 완전 다운 지표).
    "ClusterStatusRed":   "SEV-1",

    # SEV-2: 에러 급증, 서비스 품질 심각 저하
    "ELB5XX":                "SEV-2",
    "HTTPCode_ELB_5XX_Count": "SEV-2",
    "CLB5XX":                "SEV-2",
    "Errors":                "SEV-2",
    "UnHealthyHostCount":    "SEV-2",
    "Api5XXError":           "SEV-2",
    "Api5xx":                "SEV-2",
    "ErrorPortAllocation":   "SEV-2",
    "TargetConnectionError": "SEV-2",

    # SEV-3: 리소스 포화 근접, 조치 안 하면 장애 가능
    "CPU":                "SEV-3",
    "Memory":             "SEV-3",
    "Disk":               "SEV-3",
    "FreeMemoryGB":       "SEV-3",
    "FreeStorageGB":      "SEV-3",
    "CPUUtilization":     "SEV-3",
    "mem_used_percent":   "SEV-3",
    "disk_used_percent":  "SEV-3",
    "FreeableMemory":     "SEV-3",
    "FreeStorageSpace":   "SEV-3",
    "FreeLocalStorageGB": "SEV-3",
    "FreeLocalStorage":  "SEV-3",
    "EngineCPU":          "SEV-3",
    "ACUUtilization":     "SEV-3",
    "DaysToExpiry":       "SEV-3",
    "ReplicaLag":         "SEV-3",
    "ReaderReplicaLag":   "SEV-3",
    "PacketsDropCount":   "SEV-3",
    "Evictions":          "SEV-3",
    "OSFreeStorageSpace": "SEV-3",

    # SEV-4: 성능 저하, 사용자 체감 가능하나 서비스 중단 아님
    "TGResponseTime":       "SEV-4",
    "ReadLatency":          "SEV-4",
    "WriteLatency":         "SEV-4",
    "TargetResponseTime":   "SEV-4",
    "Duration":             "SEV-4",
    "ApiLatency":           "SEV-4",
    "ELB4XX":               "SEV-4",
    "Api4XXError":          "SEV-4",
    "Api4xx":               "SEV-4",
    "BurstCreditBalance":   "SEV-4",

    # SEV-5: 트래픽/용량 참고 지표, 추세 모니터링
    "Connections":            "SEV-5",
    "TCPClientReset":         "SEV-5",
    "TCPTargetReset":         "SEV-5",
    "TCP_Client_Reset_Count": "SEV-5",
    "TCP_Target_Reset_Count": "SEV-5",
    "RequestCount":           "SEV-5",
    "DatabaseConnections":    "SEV-5",
    "CurrConnections":        "SEV-5",
    "ProcessedBytes":         "SEV-5",
    "ActiveFlowCount":        "SEV-5",
    "NewFlowCount":           "SEV-5",
    "ConnectionAttempts":     "SEV-5",
    "RequestCountPerTarget":  "SEV-5",
    "ServerlessDatabaseCapacity": "SEV-5",
    "DatabaseMemoryUsagePercentage": "SEV-2",
}


SEVERITIES: tuple[str, ...] = ("SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5")


def is_valid_severity(value) -> bool:
    """`SEV-1`~`SEV-5`인가. 태그·설명 메타데이터·API 입력 모두 이 집합 밖은 받지 않는다."""
    return isinstance(value, str) and value in SEVERITIES


def get_severity(metric_key: str) -> str:
    """메트릭 키에 대한 기본 Severity 등급 반환.

    Disk_root 등 Disk_ prefix, disk_used_percent_ prefix 모두 SEV-3 (포화도).
    미정의 메트릭은 SEV-5 폴백.
    """
    if metric_key.startswith("Disk_") or metric_key.startswith("disk_used_percent_"):
        return "SEV-3"
    return _DEFAULT_SEVERITY.get(metric_key, "SEV-5")
