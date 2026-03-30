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
    }
    return mapping.get(metric_name, metric_name)
