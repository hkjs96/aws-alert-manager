"""
Alarm Manager - CloudWatch Alarm 자동 생성/삭제/동기화 모듈

Monitoring=on 태그 감지 시 리소스 유형별 CloudWatch Alarm을 자동 생성하고,
태그 제거 시 삭제한다.

알람 네이밍 규칙: {resource_id}-{metric}-{env}
  예: i-1234567890abcdef0-CPU-prod
"""

import functools
import json
import logging
import math
import os
import re

import boto3
from botocore.exceptions import ClientError

from common.tag_resolver import (
    disk_path_to_tag_suffix,
    get_threshold,
    is_threshold_off,
    tag_suffix_to_disk_path,
)

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


def _get_env() -> str:
    return os.environ.get("ENVIRONMENT", "prod")


def _get_sns_alert_arn() -> str:
    return os.environ.get("SNS_TOPIC_ARN_ALERT", "")


def _alarm_name(resource_id: str, metric: str) -> str:
    """레거시 알람 이름 생성 (삭제 호환용): {resource_id}-{metric}-{env}"""
    return f"{resource_id}-{metric}-{_get_env()}"


# 메트릭별 표시이름/방향/단위 매핑
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
}


def _pretty_alarm_name(
    resource_type: str,
    resource_id: str,
    resource_name: str,
    metric: str,
    threshold: float,
) -> str:
    """
    알람 이름 생성 (새 포맷).
    [EC2] my-server CPU >80% (i-0fd4bf757020d3714)

    255자 초과 시 label → display_metric 순으로 truncate.
    resource_id 부분은 알람 검색/매칭에 필수이므로 절대 truncate하지 않음.
    """
    _MAX_ALARM_NAME = 255
    _ELLIPSIS = "..."

    direction, unit = _METRIC_DISPLAY.get(
        metric.split("-")[0] if metric.startswith("Disk-") else metric,
        ("unknown", ">", ""),
    )[1:]
    display_name = _METRIC_DISPLAY.get(
        metric.split("-")[0] if metric.startswith("Disk-") else metric,
        ("unknown", ">", ""),
    )[0]
    # Disk-root → disk_used_percent(/) , Disk-data → disk_used_percent(/data)
    if metric.startswith("Disk-"):
        path_part = metric[len("Disk-"):]
        display_metric = f"{display_name}(/{path_part})" if path_part != "root" else f"{display_name}(/)"
    else:
        display_metric = display_name

    # threshold 표시: 정수면 소수점 없이, 소수면 불필요한 0 제거
    if threshold == int(threshold):
        thr_str = str(int(threshold))
    else:
        thr_str = f"{threshold:g}"

    label = resource_name or resource_id

    # 고정 부분 (절대 truncate 불가): prefix + threshold_part + suffix
    prefix = f"[{resource_type}] "
    threshold_part = f" {direction}{thr_str}{unit} "
    short_id = _shorten_elb_resource_id(resource_id, resource_type)
    suffix = f"({short_id})"

    fixed_len = len(prefix) + len(threshold_part) + len(suffix)
    available = _MAX_ALARM_NAME - fixed_len

    # 1단계: label + display_metric이 available 이내면 그대로
    if len(label) + 1 + len(display_metric) <= available:
        return f"{prefix}{label} {display_metric}{threshold_part}{suffix}"

    # 2단계: label truncate (display_metric 보존)
    # " " + display_metric 공간 확보
    label_budget = available - 1 - len(display_metric)
    if label_budget >= len(_ELLIPSIS) + 1:
        truncated_label = label[: label_budget - len(_ELLIPSIS)] + _ELLIPSIS
        return f"{prefix}{truncated_label} {display_metric}{threshold_part}{suffix}"

    # 3단계: label을 최소("...")로 고정하고 display_metric도 truncate
    min_label = _ELLIPSIS
    metric_budget = available - len(min_label) - 1
    if metric_budget >= len(_ELLIPSIS) + 1:
        truncated_metric = display_metric[: metric_budget - len(_ELLIPSIS)] + _ELLIPSIS
        return f"{prefix}{min_label} {truncated_metric}{threshold_part}{suffix}"

    # 4단계: 극단적 케이스 — label/display_metric 모두 최소
    return f"{prefix}{min_label} {_ELLIPSIS}{threshold_part}{suffix}"


def _build_alarm_description(
    resource_type: str,
    resource_id: str,
    metric_key: str,
    human_prefix: str = "",
) -> str:
    """AlarmDescription에 JSON 메타데이터를 포함하여 생성.

    포맷: {human_prefix} | {"metric_key":"CPU","resource_id":"i-xxx","resource_type":"EC2"}
    최대 1024자 (CloudWatch API 제한).
    """
    metadata = json.dumps({
        "metric_key": metric_key,
        "resource_id": resource_id,
        "resource_type": resource_type,
    }, separators=(",", ":"))
    if human_prefix:
        desc = f"{human_prefix} | {metadata}"
    else:
        desc = metadata
    return desc[:1024]


def _parse_alarm_metadata(description: str) -> dict | None:
    """AlarmDescription에서 JSON 메타데이터를 파싱.

    Returns:
        {"metric_key": ..., "resource_id": ..., "resource_type": ...} 또는 None
    """
    if not description:
        return None
    # JSON은 " | " 구분자 뒤에 위치
    idx = description.rfind(" | {")
    json_str = description[idx + 3:] if idx >= 0 else description
    try:
        data = json.loads(json_str)
        if "metric_key" in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _find_alarms_for_resource(
    resource_id: str,
    resource_type: str = "",
) -> list[str]:
    """resource_id에 해당하는 모든 알람 이름 조회 (새/레거시 포맷).

    검색 전략 (전체 풀스캔 금지 - 거버넌스 규칙 6):
    1) 레거시: AlarmNamePrefix=resource_id (레거시 알람 호환)
    2) 새 포맷: AlarmNamePrefix="[{resource_type}] " + suffix 필터
       resource_type 지정 시 해당 타입만, 미지정 시 EC2/RDS/ELB 검색
    """
    cw = _get_cw_client()
    seen: set[str] = set()
    alarm_names: list[str] = []
    short_id = _shorten_elb_resource_id(resource_id, resource_type)
    suffixes = {f"({short_id})"}
    if short_id != resource_id:
        suffixes.add(f"({resource_id})")  # 레거시 Full_ARN 호환

    def _collect(prefix: str, filter_suffix: bool = False) -> None:
        try:
            paginator = cw.get_paginator("describe_alarms")
            for page in paginator.paginate(AlarmNamePrefix=prefix):
                for a in page.get("MetricAlarms", []):
                    name = a["AlarmName"]
                    if filter_suffix and not any(name.endswith(s) for s in suffixes):
                        continue
                    if name not in seen:
                        seen.add(name)
                        alarm_names.append(name)
        except ClientError as e:
            logger.error(
                "Failed to list alarms prefix=%s for %s: %s",
                prefix, resource_id, e,
            )

    # 1) 레거시 prefix 검색
    _collect(resource_id)

    # 2) 새 포맷: resource_type prefix 기반 검색 + suffix 필터
    type_prefixes = (
        [f"[{resource_type}] "]
        if resource_type
        else [f"[{rt}] " for rt in ("EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS")]
    )
    for p in type_prefixes:
        _collect(p, filter_suffix=True)

    # 3) 레거시 [ELB] prefix 호환: ALB/NLB/TG는 기존 [ELB] 알람도 검색
    if resource_type in ("ALB", "NLB", "TG"):
        _collect("[ELB] ", filter_suffix=True)

    return alarm_names


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
    "RDS": {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency"},
    "ALB": {"RequestCount", "ELB5XX", "TargetResponseTime"},
    "NLB": {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"},
    "TG": {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"},
    "AuroraRDS": {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag", "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity"},
}

# resource_type별 CloudWatch 네임스페이스 목록
_NAMESPACE_MAP: dict[str, list[str]] = {
    "EC2": ["AWS/EC2", "CWAgent"],
    "RDS": ["AWS/RDS"],
    "ALB": ["AWS/ApplicationELB"],
    "NLB": ["AWS/NetworkELB"],
    "TG": ["AWS/ApplicationELB", "AWS/NetworkELB"],
    "AuroraRDS": ["AWS/RDS"],
}

# resource_type별 디멘션 키
_DIMENSION_KEY_MAP: dict[str, str] = {
    "EC2": "InstanceId",
    "RDS": "DBInstanceIdentifier",
    "ALB": "LoadBalancer",
    "NLB": "LoadBalancer",
    "TG": "TargetGroup",
    "AuroraRDS": "DBInstanceIdentifier",
}

# AWS 태그 허용 문자 패턴 (메트릭 이름 부분)
_TAG_ALLOWED_CHARS = re.compile(
    r'^[a-zA-Z0-9 _.:/=+\-@]+$'
)


def _get_hardcoded_metric_keys(resource_type: str, resource_tags: dict | None = None) -> set[str]:
    """resource_type과 resource_tags 기반으로 하드코딩 메트릭 키 집합을 반환.

    _get_alarm_defs() 결과에서 동적으로 추출하여 NLB TG 등 LB 타입별 차이를 반영한다.
    """
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    return {d["metric"] for d in alarm_defs}


def _parse_threshold_tags(
    resource_tags: dict,
    resource_type: str,
) -> dict[str, tuple[float, str]]:
    """Threshold_* 태그에서 하드코딩 목록에 없는 동적 메트릭을 추출.

    태그 키 형식:
    - Threshold_{MetricName}={Value} → GreaterThanThreshold (기본)
    - Threshold_LT_{MetricName}={Value} → LessThanThreshold (낮을수록 위험)

    Args:
        resource_tags: 리소스 태그 딕셔너리
        resource_type: EC2 / RDS / ELB

    Returns:
        {metric_name: (threshold_value, comparison_operator)} 딕셔너리 (동적 메트릭만)
    """
    hardcoded = _get_hardcoded_metric_keys(resource_type, resource_tags)
    result: dict[str, tuple[float, str]] = {}

    for key, value in resource_tags.items():
        if not key.startswith("Threshold_"):
            continue
        # Threshold_Disk_* 패턴은 기존 Disk 로직에서 처리
        if key.startswith("Threshold_Disk_"):
            continue
        # Threshold_FreeMemoryPct는 퍼센트 기반 메모리 임계치 전용
        if key == "Threshold_FreeMemoryPct":
            continue

        raw_metric = key[len("Threshold_"):]

        # LT_ prefix 감지: Threshold_LT_{MetricName} → LessThanThreshold
        if raw_metric.startswith("LT_"):
            metric_name = raw_metric[len("LT_"):]
            comparison = "LessThanThreshold"
        else:
            metric_name = raw_metric
            comparison = "GreaterThanThreshold"

        # 메트릭 이름 최소 1자
        if not metric_name:
            continue
        # 하드코딩 목록에 있으면 skip (내부 키 또는 CW metric_name 별칭)
        if metric_name in hardcoded or _metric_name_to_key(metric_name) in hardcoded:
            continue
        # 태그 키 128자 제한
        if len(key) > 128:
            logger.warning(
                "Skipping dynamic tag %s: key exceeds 128 chars",
                key,
            )
            continue
        # 태그 허용 문자 검증
        if not _TAG_ALLOWED_CHARS.match(metric_name):
            logger.warning(
                "Skipping dynamic tag %s: invalid characters in metric name",
                key,
            )
            continue
        # off 값 명시적 스킵 (대소문자 무관)
        if value.strip().lower() == "off":
            logger.info(
                "Skipping dynamic tag %s: alarm explicitly disabled (off)",
                key,
            )
            continue
        # 값 검증: 양의 유한 숫자
        try:
            val = float(value)
            if not math.isfinite(val) or val <= 0:
                logger.warning(
                    "Skipping dynamic tag %s=%s: not a positive number",
                    key, value,
                )
                continue
            result[metric_name] = (val, comparison)
        except (ValueError, TypeError):
            logger.warning(
                "Skipping dynamic tag %s=%s: non-numeric value",
                key, value,
            )

    return result


def _select_best_dimensions(
    metrics: list[dict],
    primary_dim_key: str,
) -> list[dict]:
    """list_metrics 결과에서 최적 디멘션 조합 선택.

    우선순위:
    1. Primary_Dimension_Key만 포함된 조합
    2. AZ 미포함 + 디멘션 수 최소
    3. 디멘션 수 최소 (AZ 포함 허용)
    """
    if not metrics:
        return []

    # 1순위: primary_dim_key만 포함된 조합
    for m in metrics:
        dims = m["Dimensions"]
        if len(dims) == 1 and dims[0]["Name"] == primary_dim_key:
            return dims

    # 2순위: AZ 미포함 조합 중 디멘션 수 최소
    no_az = [
        m["Dimensions"] for m in metrics
        if not any(d["Name"] == "AvailabilityZone" for d in m["Dimensions"])
    ]
    if no_az:
        return min(no_az, key=len)

    # 3순위: 디멘션 수 최소 (AZ 포함 허용)
    return min((m["Dimensions"] for m in metrics), key=len)


def _resolve_metric_dimensions(
    resource_id: str,
    metric_name: str,
    resource_type: str,
) -> tuple[str, list[dict]] | None:
    """list_metrics API로 네임스페이스/디멘션 자동 해석.

    Args:
        resource_id: 리소스 ID
        metric_name: CloudWatch 메트릭 이름
        resource_type: EC2 / RDS / ELB

    Returns:
        (namespace, dimensions) 튜플 또는 None (미발견 시)
    """
    cw = _get_cw_client()
    namespaces = _NAMESPACE_MAP.get(resource_type, [])
    dim_key = _DIMENSION_KEY_MAP.get(resource_type, "")

    # ALB/NLB/TG는 ARN suffix를 디멘션 값으로 사용
    if resource_type in ("ALB", "NLB", "TG"):
        dim_value = _extract_elb_dimension(resource_id)
    else:
        dim_value = resource_id

    for namespace in namespaces:
        try:
            resp = cw.list_metrics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[
                    {"Name": dim_key, "Value": dim_value},
                ],
            )
            metrics = resp.get("Metrics", [])
            if metrics:
                return (namespace, _select_best_dimensions(metrics, dim_key))
        except ClientError as e:
            logger.error(
                "Failed to list_metrics for %s/%s (%s): %s",
                namespace, metric_name, resource_id, e,
            )

    logger.warning(
        "Metric %s not found in any namespace for %s (%s): skipping",
        metric_name, resource_id, resource_type,
    )
    return None


# ──────────────────────────────────────────────
# 알람 생성
# ──────────────────────────────────────────────

def _create_disk_alarms(
    resource_id: str,
    resource_type: str,
    resource_name: str,
    resource_tags: dict,
    alarm_def: dict,
    cw,
    sns_arn: str,
) -> list[str]:
    """Disk 알람 생성 로직 (CWAgent 디멘션 동적 조회)."""
    created: list[str] = []
    extra_paths = {
        tag_suffix_to_disk_path(k[len("Threshold_Disk_"):])
        for k in resource_tags
        if k.startswith("Threshold_Disk_") and k != "Threshold_Disk_root"
    }
    disk_dim_sets = _get_disk_dimensions(resource_id, extra_paths or None)
    if not disk_dim_sets:
        logger.warning(
            "Skipping Disk alarm for %s: no CWAgent metrics found. "
            "Install CWAgent and wait for first metric report.",
            resource_id,
        )
        return created

    for dim_set in disk_dim_sets:
        path = next((d["Value"] for d in dim_set if d["Name"] == "path"), "/")
        suffix = path.lstrip("/") or "root"
        alarm_metric = f"Disk_{suffix}"
        if is_threshold_off(resource_tags, alarm_metric):
            logger.info(
                "Skipping Disk alarm for %s path %s: threshold set to off",
                resource_id, path,
            )
            continue
        disk_threshold = get_threshold(resource_tags, alarm_metric)
        disk_metric_label = f"Disk-{suffix}"
        name = _pretty_alarm_name(
            resource_type, resource_id, resource_name,
            disk_metric_label, disk_threshold,
        )
        _DISK_DIM_KEYS = {"InstanceId", "device", "fstype", "path"}
        clean_dims = [d for d in dim_set if d["Name"] in _DISK_DIM_KEYS]
        desc = _build_alarm_description(
            resource_type, resource_id, alarm_metric,
            f"Auto-created by AWS Monitoring Engine for EC2 {resource_id} disk {path}",
        )
        try:
            cw.put_metric_alarm(
                AlarmName=name,
                AlarmDescription=desc,
                Namespace="CWAgent",
                MetricName="disk_used_percent",
                Dimensions=clean_dims,
                Statistic="Average",
                Period=alarm_def["period"],
                EvaluationPeriods=alarm_def["evaluation_periods"],
                Threshold=disk_threshold,
                ComparisonOperator=alarm_def["comparison"],
                ActionsEnabled=True,
                AlarmActions=[sns_arn] if sns_arn else [],
                OKActions=[sns_arn] if sns_arn else [],
                TreatMissingData="missing",
            )
            logger.info("Created disk alarm: %s (path=%s, threshold=%.2f)", name, path, disk_threshold)
            created.append(name)
        except ClientError as e:
            logger.error("Failed to create disk alarm %s: %s", name, e)
    return created


def _build_dimensions(
    alarm_def: dict,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> list[dict]:
    """리소스 유형별 CloudWatch Dimensions 리스트 생성.

    - TG: TargetGroup + LoadBalancer 복합 디멘션
    - ALB/NLB: LoadBalancer 단일 디멘션
    - EC2/RDS 등: {dim_key: resource_id} 단일 디멘션
    - alarm_def의 extra_dimensions 추가
    """
    dim_key = alarm_def["dimension_key"]

    if resource_type == "TG":
        dimensions = [
            {"Name": "TargetGroup", "Value": _extract_elb_dimension(resource_id)},
            {"Name": "LoadBalancer", "Value": _extract_elb_dimension(resource_tags["_lb_arn"])},
        ]
    elif resource_type in ("ALB", "NLB"):
        dimensions = [{"Name": dim_key, "Value": _extract_elb_dimension(resource_id)}]
    else:
        dimensions = [{"Name": dim_key, "Value": resource_id}]

    dimensions.extend(alarm_def.get("extra_dimensions", []))
    return dimensions


def _resolve_tg_namespace(alarm_def: dict, resource_tags: dict) -> str:
    """TG 리소스의 CloudWatch namespace를 동적 결정.

    _lb_type == "network" → AWS/NetworkELB, 그 외 → alarm_def["namespace"].
    """
    if resource_tags.get("_lb_type") == "network":
        return "AWS/NetworkELB"
    return alarm_def["namespace"]


def _resolve_free_memory_threshold(
    resource_tags: dict,
) -> tuple[float, float]:
    """FreeMemoryGB 임계치를 퍼센트 또는 GB 기반으로 해석.

    우선순위:
    1. Threshold_FreeMemoryPct 태그 (명시적 퍼센트, 프로비저닝 인스턴스만)
    2. _total_memory_bytes 존재 + 비서버리스 시 HARDCODED_DEFAULTS["FreeMemoryPct"] 자동 적용
    3. Threshold_FreeMemoryGB 태그 또는 HARDCODED_DEFAULTS["FreeMemoryGB"] (절대값 폴백)

    Serverless v2는 ACU에 따라 메모리가 동적 변동하므로 퍼센트 기반 임계치를 적용하지 않는다.
    Serverless v2에서는 ACUUtilization 알람이 메모리 압박을 대신 감지한다.

    Returns:
        (display_threshold_gb, cw_threshold_bytes) 튜플.
    """
    is_serverless = resource_tags.get("_is_serverless_v2") == "true"
    total_mem_raw = resource_tags.get("_total_memory_bytes")

    # Serverless v2: 퍼센트 기반 스킵 → GB 절대값만 사용
    if is_serverless:
        gb = get_threshold(resource_tags, "FreeMemoryGB")
        return (gb, gb * 1073741824)

    # 1단계: 명시적 Threshold_FreeMemoryPct 태그
    pct_raw = resource_tags.get("Threshold_FreeMemoryPct")
    if pct_raw is not None:
        try:
            pct = float(pct_raw)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid Threshold_FreeMemoryPct=%r (non-numeric): falling back",
                pct_raw,
            )
        else:
            if not (0 < pct < 100):
                logger.warning(
                    "Invalid Threshold_FreeMemoryPct=%s (must be 0 < pct < 100): falling back",
                    pct_raw,
                )
            elif total_mem_raw is None:
                logger.warning(
                    "Threshold_FreeMemoryPct=%s but _total_memory_bytes missing: falling back to GB",
                    pct_raw,
                )
            else:
                total_mem = float(total_mem_raw)
                cw_bytes = (pct / 100) * total_mem
                display_gb = round(cw_bytes / 1073741824, 2)
                return (display_gb, cw_bytes)

    # 2단계: _total_memory_bytes 있으면 기본 퍼센트(20%) 자동 적용
    if total_mem_raw is not None:
        from common import HARDCODED_DEFAULTS
        default_pct = HARDCODED_DEFAULTS.get("FreeMemoryPct", 20.0)
        total_mem = float(total_mem_raw)
        cw_bytes = (default_pct / 100) * total_mem
        display_gb = round(cw_bytes / 1073741824, 2)
        return (display_gb, cw_bytes)

    # 3단계: GB 절대값 폴백
    gb = get_threshold(resource_tags, "FreeMemoryGB")
    return (gb, gb * 1073741824)



def _create_standard_alarm(
    alarm_def: dict,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    cw,
) -> str | None:
    """단일 표준(하드코딩) 알람 생성. 성공 시 알람 이름 반환."""
    sns_arn = _get_sns_alert_arn()
    resource_name = resource_tags.get("Name", "")
    metric = alarm_def["metric"]

    # FreeMemoryGB: 퍼센트 기반 임계치 해석
    if metric == "FreeMemoryGB":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    dimensions = _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)

    namespace = (
        _resolve_tg_namespace(alarm_def, resource_tags)
        if resource_type == "TG"
        else alarm_def["namespace"]
    )

    name = _pretty_alarm_name(
        resource_type, resource_id, resource_name,
        metric, threshold,
    )
    desc = _build_alarm_description(
        resource_type, resource_id, metric,
        f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
    )
    try:
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=desc,
            Namespace=namespace,
            MetricName=alarm_def["metric_name"],
            Dimensions=dimensions,
            Statistic=alarm_def["stat"],
            Period=alarm_def["period"],
            EvaluationPeriods=alarm_def["evaluation_periods"],
            Threshold=cw_threshold,
            ComparisonOperator=alarm_def["comparison"],
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="missing",
        )
        logger.info("Created alarm: %s (threshold=%.2f)", name, threshold)
        return name
    except ClientError as e:
        logger.error("Failed to create alarm %s: %s", name, e)
        return None


def create_alarms_for_resource(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> list[str]:
    """
    리소스에 대한 CloudWatch Alarm을 생성한다.

    Args:
        resource_id: 리소스 ID
        resource_type: EC2 / RDS / ELB
        resource_tags: 리소스 태그 딕셔너리

    Returns:
        생성된 알람 이름 목록
    """
    cw = _get_cw_client()
    sns_arn = _get_sns_alert_arn()
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    created: list[str] = []
    resource_name = resource_tags.get("Name", "")

    # 기존 알람 삭제 (레거시 + 새 포맷 모두)
    _delete_all_alarms_for_resource(resource_id, resource_type)

    for alarm_def in alarm_defs:
        if alarm_def.get("dynamic_dimensions") and alarm_def["metric"] == "Disk":
            disk_names = _create_disk_alarms(
                resource_id, resource_type, resource_name,
                resource_tags, alarm_def, cw, sns_arn,
            )
            created.extend(disk_names)
        else:
            if is_threshold_off(resource_tags, alarm_def["metric"]):
                logger.info(
                    "Skipping alarm for %s metric %s: threshold set to off",
                    resource_id, alarm_def["metric"],
                )
                continue
            name = _create_standard_alarm(
                alarm_def, resource_id, resource_type, resource_tags, cw,
            )
            if name:
                created.append(name)

    # 동적 태그 알람 생성 (하드코딩 목록 외 Threshold_* 태그)
    dynamic_metrics = _parse_threshold_tags(resource_tags, resource_type)
    for metric_name, (threshold, comparison) in dynamic_metrics.items():
        _create_dynamic_alarm(
            resource_id, resource_type, resource_name,
            metric_name, threshold, cw, sns_arn, created,
            comparison=comparison,
        )

    return created


def _shorten_elb_resource_id(resource_id: str, resource_type: str) -> str:
    """ALB/NLB/TG ARN에서 짧은 식별자(name/hash)를 추출.

    - ALB: arn:...loadbalancer/app/{name}/{hash} → {name}/{hash}
    - NLB: arn:...loadbalancer/net/{name}/{hash} → {name}/{hash}
    - TG:  arn:...targetgroup/{name}/{hash}      → {name}/{hash}
    - EC2/RDS 또는 ARN이 아닌 입력: 그대로 반환 (방어적 처리)
    """
    if resource_type not in ("ALB", "NLB", "TG"):
        return resource_id
    if not resource_id:
        return resource_id

    if resource_type in ("ALB", "NLB"):
        # loadbalancer/app/{name}/{hash} 또는 loadbalancer/net/{name}/{hash}
        for prefix in ("loadbalancer/app/", "loadbalancer/net/"):
            idx = resource_id.find(prefix)
            if idx >= 0:
                return resource_id[idx + len(prefix):]
    elif resource_type == "TG":
        # targetgroup/{name}/{hash}
        marker = ":targetgroup/"
        idx = resource_id.find(marker)
        if idx >= 0:
            return resource_id[idx + len(marker):]
        # 이미 short_id 형태이거나 "targetgroup/" 접두사 없는 경우
        marker_no_colon = "targetgroup/"
        if resource_id.startswith(marker_no_colon):
            return resource_id[len(marker_no_colon):]

    return resource_id


def _extract_elb_dimension(elb_arn: str) -> str:
    """
    ALB/NLB/TG ARN에서 CloudWatch Dimension 값 추출.
    arn:aws:elasticloadbalancing:...:loadbalancer/app/my-alb/1234
    → app/my-alb/1234
    arn:aws:elasticloadbalancing:...:targetgroup/my-tg/1234
    → targetgroup/my-tg/1234
    """
    # LB: loadbalancer/ prefix 제거 → app/... 또는 net/...
    parts = elb_arn.split("loadbalancer/", 1)
    if len(parts) == 2:
        return parts[1]
    # TG: targetgroup/ prefix 유지 (CloudWatch 디멘션 규칙)
    parts = elb_arn.split(":targetgroup/", 1)
    if len(parts) == 2:
        return "targetgroup/" + parts[1]
    return elb_arn


def _create_dynamic_alarm(
    resource_id: str,
    resource_type: str,
    resource_name: str,
    metric_name: str,
    threshold: float,
    cw,
    sns_arn: str,
    created: list[str],
    comparison: str = "GreaterThanThreshold",
) -> None:
    """동적 태그 메트릭에 대한 알람 생성.

    list_metrics API로 네임스페이스/디멘션을 해석하고 알람을 생성한다.
    comparison: "GreaterThanThreshold" (기본) 또는 "LessThanThreshold" (Threshold_LT_ prefix)
    """
    resolved = _resolve_metric_dimensions(
        resource_id, metric_name, resource_type,
    )
    if resolved is None:
        return

    namespace, dimensions = resolved
    thr_str = str(int(threshold)) if threshold == int(threshold) else f"{threshold:g}"
    direction = "<" if comparison == "LessThanThreshold" else ">"
    label = resource_name or resource_id

    # 255자 제한 준수 (거버넌스 §6)
    _MAX_ALARM_NAME = 255
    _ELLIPSIS = "..."
    prefix = f"[{resource_type}] "
    threshold_part = f" {direction}{thr_str} "
    short_id = _shorten_elb_resource_id(resource_id, resource_type)
    suffix = f"({short_id})"
    fixed_len = len(prefix) + len(threshold_part) + len(suffix)
    available = _MAX_ALARM_NAME - fixed_len

    if len(label) + 1 + len(metric_name) <= available:
        name = f"{prefix}{label} {metric_name}{threshold_part}{suffix}"
    else:
        label_budget = available - 1 - len(metric_name)
        if label_budget >= len(_ELLIPSIS) + 1:
            label = label[: label_budget - len(_ELLIPSIS)] + _ELLIPSIS
            name = f"{prefix}{label} {metric_name}{threshold_part}{suffix}"
        else:
            min_label = _ELLIPSIS
            metric_budget = available - len(min_label) - 1
            if metric_budget >= len(_ELLIPSIS) + 1:
                trunc_metric = metric_name[: metric_budget - len(_ELLIPSIS)] + _ELLIPSIS
                name = f"{prefix}{min_label} {trunc_metric}{threshold_part}{suffix}"
            else:
                name = f"{prefix}{min_label} {_ELLIPSIS}{threshold_part}{suffix}"

    try:
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=_build_alarm_description(
                resource_type, resource_id, metric_name,
                f"Auto-created dynamic alarm for {resource_type} {resource_id} metric={metric_name}",
            ),
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=threshold,
            ComparisonOperator=comparison,
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="missing",
        )
        logger.info(
            "Created dynamic alarm: %s (metric=%s, threshold=%.2f, comparison=%s)",
            name, metric_name, threshold, comparison,
        )
        created.append(name)
    except ClientError as e:
        logger.error(
            "Failed to create dynamic alarm %s: %s", name, e,
        )


def _get_disk_dimensions(instance_id: str, extra_paths: set[str] | None = None) -> list[list[dict]]:
    """
    CloudWatch에서 해당 인스턴스의 실제 disk_used_percent dimension 조합 조회.

    기본적으로 '/' (root)만 반환.
    extra_paths에 추가 경로가 있으면 해당 경로도 포함.

    Args:
        instance_id: EC2 인스턴스 ID
        extra_paths: 태그 기반 추가 모니터링 경로 (예: {"/data", "/var"})

    Returns:
        dimension 조합 리스트. 조회 실패 또는 메트릭 없으면 빈 리스트 반환.
    """
    target_paths = {"/"}
    if extra_paths:
        target_paths.update(extra_paths)

    cw = _get_cw_client()
    try:
        resp = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        )
        metrics = resp.get("Metrics", [])
        if not metrics:
            logger.warning(
                "No CWAgent disk_used_percent metrics found for %s. "
                "CWAgent may not be installed or not yet reporting.",
                instance_id,
            )
            return []

        # path 기준으로 필터링 (target_paths에 있는 것만) + 중복 제거
        seen_paths = set()
        result = []
        for m in metrics:
            path = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "path"), None)
            if path and path in target_paths and path not in seen_paths:
                seen_paths.add(path)
                result.append(m["Dimensions"])

        missing = target_paths - seen_paths
        if missing:
            logger.warning(
                "Disk paths not found in CWAgent metrics for %s: %s",
                instance_id, missing,
            )
        return result
    except ClientError as e:
        logger.error("Failed to list disk metrics for %s: %s", instance_id, e)
        return []


# ──────────────────────────────────────────────
# 개별 알람 재생성 헬퍼
# ──────────────────────────────────────────────

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
        "TargetResponseTime": "TargetResponseTime",
        "TCP_Client_Reset_Count": "TCPClientReset",
        "TCP_Target_Reset_Count": "TCPTargetReset",
        "RequestCountPerTarget": "RequestCountPerTarget",
        "FreeLocalStorage": "FreeLocalStorageGB",
        "AuroraReplicaLagMaximum": "ReplicaLag",
        "AuroraReplicaLag": "ReaderReplicaLag",
        "ACUUtilization": "ACUUtilization",
        "ServerlessDatabaseCapacity": "ServerlessDatabaseCapacity",
    }
    return mapping.get(metric_name, metric_name)


def _resolve_metric_key(alarm_info: dict) -> str:
    """알람 정보에서 메트릭 키를 해석 (메타데이터 우선, 폴백으로 MetricName)."""
    desc = alarm_info.get("AlarmDescription", "")
    metadata = _parse_alarm_metadata(desc)
    if metadata and "metric_key" in metadata:
        return metadata["metric_key"]
    # 레거시 폴백: MetricName → 내부 키
    return _metric_name_to_key(alarm_info.get("MetricName", ""))


def _create_single_alarm(
    metric: str,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> None:
    """전체 삭제 없이 단일 메트릭 알람만 생성 (result["created"] 처리용)."""
    cw = _get_cw_client()
    sns_arn = _get_sns_alert_arn()
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    resource_name = resource_tags.get("Name", "")

    alarm_def = next((d for d in alarm_defs if d["metric"] == metric), None)
    if alarm_def is None:
        logger.warning("No alarm definition found for metric %s", metric)
        return

    # FreeMemoryGB: 퍼센트 기반 임계치 해석
    if metric == "FreeMemoryGB":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    dimensions = _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)

    namespace = (
        _resolve_tg_namespace(alarm_def, resource_tags)
        if resource_type == "TG"
        else alarm_def["namespace"]
    )

    name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)
    desc = _build_alarm_description(
        resource_type, resource_id, metric,
        f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
    )
    try:
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=desc,
            Namespace=namespace,
            MetricName=alarm_def["metric_name"],
            Dimensions=dimensions,
            Statistic=alarm_def["stat"],
            Period=alarm_def["period"],
            EvaluationPeriods=alarm_def["evaluation_periods"],
            Threshold=cw_threshold,
            ComparisonOperator=alarm_def["comparison"],
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="missing",
        )
        logger.info("Created single alarm: %s (threshold=%.2f)", name, threshold)
    except ClientError as e:
        logger.error("Failed to create single alarm %s: %s", name, e)


def _recreate_alarm_by_name(
    alarm_name: str,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> None:
    """알람 이름에서 메트릭 타입을 파악하여 해당 알람만 삭제 후 재생성.

    Disk 알람의 경우 기존 Dimensions(path, device, fstype 등)를 재사용한다.
    """
    cw = _get_cw_client()
    sns_arn = _get_sns_alert_arn()
    resource_name = resource_tags.get("Name", "")

    # 1. 기존 알람 설정 조회 (Dimensions 재사용 목적)
    try:
        resp = cw.describe_alarms(AlarmNames=[alarm_name])
        existing = resp.get("MetricAlarms", [])
    except ClientError as e:
        logger.error("Failed to describe alarm %s: %s", alarm_name, e)
        return

    if not existing:
        logger.warning("Alarm %s not found, skipping recreate", alarm_name)
        return

    alarm_info = existing[0]
    metric_key = _resolve_metric_key(alarm_info)
    existing_dims = alarm_info.get("Dimensions", [])

    # 2. 해당 알람만 삭제
    try:
        cw.delete_alarms(AlarmNames=[alarm_name])
    except ClientError as e:
        logger.error("Failed to delete alarm %s: %s", alarm_name, e)
        return

    # 3. put_metric_alarm으로 재생성
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    alarm_def = next((d for d in alarm_defs if d["metric"] == metric_key), None)
    if alarm_def is None:
        logger.warning("No alarm definition found for metric key %s (alarm: %s)", metric_key, alarm_name)
        return

    if metric_key == "Disk":
        _recreate_disk_alarm(
            alarm_def, existing_dims, resource_id, resource_type,
            resource_name, resource_tags, cw, sns_arn,
        )
    else:
        _recreate_standard_alarm(
            alarm_def, metric_key, resource_id, resource_type,
            resource_name, resource_tags, cw, sns_arn,
        )


def _recreate_disk_alarm(
    alarm_def: dict,
    existing_dims: list[dict],
    resource_id: str,
    resource_type: str,
    resource_name: str,
    resource_tags: dict,
    cw,
    sns_arn: str,
) -> None:
    """Disk 알람 재생성 (기존 Dimensions 재사용)."""
    path = next((d["Value"] for d in existing_dims if d["Name"] == "path"), "/")
    suffix = disk_path_to_tag_suffix(path)
    threshold = get_threshold(resource_tags, f"Disk_{suffix}")
    disk_metric_label = f"Disk-{path.lstrip('/') or 'root'}"
    name = _pretty_alarm_name(resource_type, resource_id, resource_name, disk_metric_label, threshold)
    _DISK_DIM_KEYS = {"InstanceId", "device", "fstype", "path"}
    clean_dims = [d for d in existing_dims if d["Name"] in _DISK_DIM_KEYS]
    desc = _build_alarm_description(
        resource_type, resource_id, f"Disk_{suffix}",
        f"Auto-created by AWS Monitoring Engine for EC2 {resource_id} disk {path}",
    )
    try:
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=desc,
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=clean_dims,
            Statistic=alarm_def["stat"],
            Period=alarm_def["period"],
            EvaluationPeriods=alarm_def["evaluation_periods"],
            Threshold=threshold,
            ComparisonOperator=alarm_def["comparison"],
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="missing",
        )
        logger.info("Recreated disk alarm: %s (path=%s, threshold=%.2f)", name, path, threshold)
    except ClientError as e:
        logger.error("Failed to recreate disk alarm %s: %s", name, e)


def _recreate_standard_alarm(
    alarm_def: dict,
    metric_key: str,
    resource_id: str,
    resource_type: str,
    resource_name: str,
    resource_tags: dict,
    cw,
    sns_arn: str,
) -> None:
    """표준(하드코딩) 알람 재생성."""
    # FreeMemoryGB: 퍼센트 기반 임계치 해석
    if metric_key == "FreeMemoryGB":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric_key)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    dimensions = _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)

    namespace = (
        _resolve_tg_namespace(alarm_def, resource_tags)
        if resource_type == "TG"
        else alarm_def["namespace"]
    )

    name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric_key, threshold)
    desc = _build_alarm_description(
        resource_type, resource_id, metric_key,
        f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
    )
    try:
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=desc,
            Namespace=namespace,
            MetricName=alarm_def["metric_name"],
            Dimensions=dimensions,
            Statistic=alarm_def["stat"],
            Period=alarm_def["period"],
            EvaluationPeriods=alarm_def["evaluation_periods"],
            Threshold=cw_threshold,
            ComparisonOperator=alarm_def["comparison"],
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="missing",
        )
        logger.info("Recreated alarm: %s (threshold=%.2f)", name, threshold)
    except ClientError as e:
        logger.error("Failed to recreate alarm %s: %s", name, e)


# ──────────────────────────────────────────────
# 알람 삭제
# ──────────────────────────────────────────────

def _delete_all_alarms_for_resource(
    resource_id: str,
    resource_type: str = "",
) -> list[str]:
    """리소스의 모든 알람 삭제 (레거시 + 새 포맷). 내부용."""
    cw = _get_cw_client()
    alarm_names = _find_alarms_for_resource(resource_id, resource_type)
    if not alarm_names:
        return []
    deleted = []
    try:
        # CloudWatch delete_alarms 최대 100개씩
        for i in range(0, len(alarm_names), 100):
            cw.delete_alarms(AlarmNames=alarm_names[i:i+100])
        logger.info("Deleted alarms: %s", alarm_names)
        deleted = alarm_names
    except ClientError as e:
        logger.error("Failed to delete alarms for %s: %s", resource_id, e)
    return deleted


def delete_alarms_for_resource(
    resource_id: str,
    resource_type: str,
) -> list[str]:
    """
    리소스에 대한 CloudWatch Alarm을 삭제한다.
    레거시 포맷과 새 포맷 모두 검색하여 삭제.

    Returns:
        삭제된 알람 이름 목록
    """
    return _delete_all_alarms_for_resource(resource_id, resource_type)


# ──────────────────────────────────────────────
# 알람 동기화 (Daily Monitor용)
# ──────────────────────────────────────────────

def sync_alarms_for_resource(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> dict:
    """
    리소스의 알람이 현재 태그 임계치와 일치하는지 확인하고 불일치 시 업데이트.
    메타데이터 기반 매칭: AlarmDescription JSON에서 metric_key를 파싱하여 매칭.

    Returns:
        {"created": [...], "updated": [...], "ok": [...], "deleted": [...]}
    """
    result: dict[str, list] = {
        "created": [], "updated": [], "ok": [], "deleted": [],
    }

    # 현재 알람 이름 목록 조회
    existing_names = _find_alarms_for_resource(resource_id, resource_type)

    if not existing_names:
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags)
        result["created"] = created
        return result

    # describe_alarms 1회 호출로 전체 알람 정보 캐싱
    alarm_map = _describe_alarms_batch(existing_names)

    # 메타데이터 기반으로 metric_key → alarm_info 매핑
    key_to_alarm: dict[str, dict] = {}
    for alarm_info in alarm_map.values():
        mk = _resolve_metric_key(alarm_info)
        key_to_alarm.setdefault(mk, alarm_info)

    # 하드코딩 메트릭 동기화
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)

    # alarm_defs가 빈 리스트면 이 리소스에 알람이 불필요 → 기존 알람 삭제
    if not alarm_defs and existing_names:
        _delete_all_alarms_for_resource(resource_id, resource_type)
        return result

    needs_recreate = False
    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        if alarm_def.get("dynamic_dimensions") and metric == "Disk":
            changed = _sync_disk_alarms(
                key_to_alarm, resource_tags, result,
            )
            if changed:
                needs_recreate = True
        else:
            changed = _sync_standard_alarms(
                alarm_def, key_to_alarm, resource_tags, result,
            )
            if changed:
                needs_recreate = True

    # 하드코딩 알람 off 체크: 기존 알람 삭제
    _sync_off_hardcoded(
        alarm_defs, key_to_alarm, resource_tags, result,
    )

    # 동적 알람 동기화
    _sync_dynamic_alarms(
        key_to_alarm, resource_id, resource_type, resource_tags, result,
    )

    if needs_recreate:
        _apply_sync_changes(result, resource_id, resource_type, resource_tags, existing_names)

    return result


def _describe_alarms_batch(alarm_names: list[str]) -> dict[str, dict]:
    """알람 이름 목록으로 describe_alarms 1회 호출 (100개씩 배치)."""
    cw = _get_cw_client()
    alarm_map: dict[str, dict] = {}
    for i in range(0, len(alarm_names), 100):
        batch = alarm_names[i:i + 100]
        try:
            resp = cw.describe_alarms(AlarmNames=batch)
            for a in resp.get("MetricAlarms", []):
                alarm_map[a["AlarmName"]] = a
        except ClientError as e:
            logger.error("Failed to describe alarms batch: %s", e)
    return alarm_map


def _sync_disk_alarms(
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
) -> bool:
    """Disk 알람 동기화. 변경 필요 시 True 반환."""
    # Disk_root, Disk_data 등 Disk prefix로 시작하는 키 찾기
    disk_alarms = {k: v for k, v in key_to_alarm.items() if k.startswith("Disk")}
    if not disk_alarms:
        result["created"].append("Disk")
        return True

    changed = False
    for _mk, alarm_info in disk_alarms.items():
        name = alarm_info["AlarmName"]
        existing_thr = alarm_info.get("Threshold", 0)
        path = next(
            (d["Value"] for d in alarm_info.get("Dimensions", []) if d["Name"] == "path"),
            "/",
        )
        suffix = disk_path_to_tag_suffix(path)
        # off 태그 설정 시 _sync_off_hardcoded()에서 처리 → 여기서는 스킵
        if is_threshold_off(resource_tags, f"Disk_{suffix}"):
            continue
        expected_thr = get_threshold(resource_tags, f"Disk_{suffix}")
        if abs(existing_thr - expected_thr) > 0.001:
            result["updated"].append(name)
            changed = True
        else:
            result["ok"].append(name)
    return changed


def _sync_standard_alarms(
    alarm_def: dict,
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
) -> bool:
    """표준 메트릭 알람 동기화. 변경 필요 시 True 반환."""
    metric = alarm_def["metric"]
    # off 태그 설정 시 _sync_off_hardcoded()에서 처리 → 여기서는 스킵
    if is_threshold_off(resource_tags, metric):
        return False

    # FreeMemoryGB: 퍼센트 기반 임계치 해석
    if metric == "FreeMemoryGB":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    alarm_info = key_to_alarm.get(metric)
    if not alarm_info:
        result["created"].append(metric)
        return True

    name = alarm_info["AlarmName"]
    existing_thr = alarm_info.get("Threshold", 0)
    if abs(existing_thr - cw_threshold) > 0.001:
        result["updated"].append(name)
        return True

    result["ok"].append(name)
    return False


def _sync_off_hardcoded(
    alarm_defs: list[dict],
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
) -> None:
    """하드코딩 알람 off 체크: 기존 알람이 있으면 삭제 + deleted 추가."""
    cw = _get_cw_client()
    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        if not is_threshold_off(resource_tags, metric):
            continue
        alarm_info = key_to_alarm.get(metric)
        if not alarm_info:
            continue
        name = alarm_info["AlarmName"]
        # ok/updated 목록에서 제거 (off가 우선)
        for lst_key in ("ok", "updated", "created"):
            if name in result[lst_key]:
                result[lst_key].remove(name)
            if metric in result[lst_key]:
                result[lst_key].remove(metric)
        try:
            cw.delete_alarms(AlarmNames=[name])
            logger.info(
                "Deleted alarm %s for %s: threshold set to off",
                name, metric,
            )
        except ClientError as e:
            logger.error("Failed to delete off alarm %s: %s", name, e)
            continue
        result["deleted"].append(name)


def _sync_dynamic_alarms(
    key_to_alarm: dict[str, dict],
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    result: dict[str, list],
) -> None:
    """동적 알람 동기화: 생성/삭제/업데이트."""
    cw = _get_cw_client()
    sns_arn = _get_sns_alert_arn()
    resource_name = resource_tags.get("Name", "")
    hardcoded_keys = _get_hardcoded_metric_keys(resource_type, resource_tags)

    # 현재 태그에서 동적 메트릭 추출
    dynamic_tags = _parse_threshold_tags(resource_tags, resource_type)

    # 기존 동적 알람 식별 (metric_key가 하드코딩 목록에 없는 것)
    existing_dynamic: dict[str, dict] = {
        mk: info for mk, info in key_to_alarm.items()
        if mk not in hardcoded_keys and not mk.startswith("Disk")
    }

    # 새 동적 메트릭 → 생성
    for metric_name, (threshold, comparison) in dynamic_tags.items():
        if metric_name in existing_dynamic:
            continue
        _create_dynamic_alarm(
            resource_id, resource_type, resource_name,
            metric_name, threshold, cw, sns_arn, result["created"],
            comparison=comparison,
        )

    # 기존 동적 알람 처리
    for mk, alarm_info in existing_dynamic.items():
        name = alarm_info["AlarmName"]
        if mk not in dynamic_tags:
            # 태그 제거 → 삭제
            _delete_alarm_names(cw, [name])
            result["deleted"].append(name)
            continue
        # 임계치 비교
        existing_thr = alarm_info.get("Threshold", 0)
        tag_thr, tag_comparison = dynamic_tags[mk]
        if abs(existing_thr - tag_thr) > 0.001:
            # 임계치 변경 → 삭제 후 재생성
            _delete_alarm_names(cw, [name])
            _create_dynamic_alarm(
                resource_id, resource_type, resource_name,
                mk, tag_thr, cw, sns_arn, result["created"],
                comparison=tag_comparison,
            )
            result["updated"].append(name)
        else:
            result["ok"].append(name)


def _delete_alarm_names(cw, alarm_names: list[str]) -> None:
    """알람 이름 목록으로 삭제 (에러 로깅)."""
    try:
        cw.delete_alarms(AlarmNames=alarm_names)
    except ClientError as e:
        logger.error("Failed to delete alarms %s: %s", alarm_names, e)


def _apply_sync_changes(
    result: dict[str, list],
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    existing_names: list[str],
) -> None:
    """동기화 결과에 따라 알람 재생성/생성 적용."""
    if "Disk" in result["created"] or not existing_names:
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags)
        result["created"] = created
    else:
        for alarm_name in result["updated"]:
            _recreate_alarm_by_name(alarm_name, resource_id, resource_type, resource_tags)
        for metric in result["created"]:
            if metric != "Disk":
                _create_single_alarm(metric, resource_id, resource_type, resource_tags)
