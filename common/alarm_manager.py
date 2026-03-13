"""
Alarm Manager - CloudWatch Alarm 자동 생성/삭제/동기화 모듈

Monitoring=on 태그 감지 시 리소스 유형별 CloudWatch Alarm을 자동 생성하고,
태그 제거 시 삭제한다.

알람 네이밍 규칙: {resource_id}-{metric}-{env}
  예: i-1234567890abcdef0-CPU-prod
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from common.tag_resolver import get_threshold

logger = logging.getLogger(__name__)

_cw_client = None


def _get_cw_client():
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch")
    return _cw_client


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
    """
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

    # threshold 표시: 정수면 소수점 없이
    if threshold == int(threshold):
        thr_str = str(int(threshold))
    else:
        thr_str = f"{threshold:.1f}"

    label = resource_name or resource_id
    return f"[{resource_type}] {label} {display_metric} {direction}{thr_str}{unit} ({resource_id})"


def _find_alarms_for_resource(resource_id: str) -> list[str]:
    """resource_id가 포함된 모든 알람 이름 조회 (새/레거시 포맷 모두)."""
    cw = _get_cw_client()
    alarm_names = []

    # 새 포맷: "({resource_id})" 로 끝남 → 전체 조회 후 필터
    # 레거시 포맷: "{resource_id}-" 로 시작
    # 두 가지 모두 커버하기 위해 prefix 검색 + 전체 검색 병행

    # 1) 레거시 prefix 검색
    try:
        paginator = cw.get_paginator("describe_alarms")
        for page in paginator.paginate(AlarmNamePrefix=resource_id):
            for a in page.get("MetricAlarms", []):
                alarm_names.append(a["AlarmName"])
    except Exception as e:
        logger.error("Failed to list legacy alarms for %s: %s", resource_id, e)

    # 2) 새 포맷: 전체 알람에서 "({resource_id})" 포함 검색
    suffix = f"({resource_id})"
    try:
        paginator = cw.get_paginator("describe_alarms")
        for page in paginator.paginate(AlarmTypes=["MetricAlarm"]):
            for a in page.get("MetricAlarms", []):
                name = a["AlarmName"]
                if name.endswith(suffix) and name not in alarm_names:
                    alarm_names.append(name)
    except Exception as e:
        logger.error("Failed to list new-format alarms for %s: %s", resource_id, e)

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
]

_ELB_ALARMS = [
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
]


def _get_alarm_defs(resource_type: str) -> list[dict]:
    if resource_type == "EC2":
        return _EC2_ALARMS
    elif resource_type == "RDS":
        return _RDS_ALARMS
    elif resource_type == "ELB":
        return _ELB_ALARMS
    return []


# ──────────────────────────────────────────────
# 알람 생성
# ──────────────────────────────────────────────

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
    alarm_defs = _get_alarm_defs(resource_type)
    created = []
    resource_name = resource_tags.get("Name", "")

    # 기존 알람 삭제 (레거시 + 새 포맷 모두)
    _delete_all_alarms_for_resource(resource_id)

    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        threshold = get_threshold(resource_tags, metric)

        # RDS FreeMemoryGB/FreeStorageGB는 bytes 단위로 변환
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

        # ELB dimension은 ARN에서 추출 필요
        if resource_type == "ELB" and alarm_def["dimension_key"] == "LoadBalancer":
            dim_value = _extract_elb_dimension(resource_id)
        else:
            dim_value = resource_id

        # Disk: CWAgent에서 실제 dimension 조합 동적 조회
        if alarm_def.get("dynamic_dimensions") and metric == "Disk":
            # 태그에서 추가 모니터링 경로 파싱 (Threshold_Disk_data=90 → /data)
            from common.tag_resolver import tag_suffix_to_disk_path
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
                continue
            # 파티션별로 알람 생성 (/, /data 등)
            for dim_set in disk_dim_sets:
                path = next((d["Value"] for d in dim_set if d["Name"] == "path"), "/")
                alarm_metric = f"Disk_{path.lstrip('/') or 'root'}"
                disk_threshold = get_threshold(resource_tags, alarm_metric)
                disk_metric_label = f"Disk-{path.lstrip('/') or 'root'}"
                name = _pretty_alarm_name(
                    resource_type, resource_id, resource_name,
                    disk_metric_label, disk_threshold,
                )
                # InstanceId/device/fstype/path 만 사용 (ImageId, InstanceType 등 제외)
                _DISK_DIM_KEYS = {"InstanceId", "device", "fstype", "path"}
                clean_dims = [d for d in dim_set if d["Name"] in _DISK_DIM_KEYS]
                try:
                    cw.put_metric_alarm(
                        AlarmName=name,
                        AlarmDescription=f"Auto-created by AWS Monitoring Engine for EC2 {resource_id} disk {path}",
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
            continue

        dimensions = [{"Name": alarm_def["dimension_key"], "Value": dim_value}]
        extra_dims = alarm_def.get("extra_dimensions", [])
        dimensions.extend(extra_dims)

        name = _pretty_alarm_name(
            resource_type, resource_id, resource_name,
            metric, threshold,
        )

        try:
            cw.put_metric_alarm(
                AlarmName=name,
                AlarmDescription=f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
                Namespace=alarm_def["namespace"],
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
            created.append(name)
        except ClientError as e:
            logger.error("Failed to create alarm %s: %s", name, e)

    return created


def _extract_elb_dimension(elb_arn: str) -> str:
    """
    ALB ARN에서 CloudWatch Dimension 값 추출.
    arn:aws:elasticloadbalancing:...:loadbalancer/app/my-alb/1234
    → app/my-alb/1234
    """
    parts = elb_arn.split("loadbalancer/", 1)
    if len(parts) == 2:
        return parts[1]
    return elb_arn


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
# 알람 삭제
# ──────────────────────────────────────────────

def _delete_all_alarms_for_resource(resource_id: str) -> list[str]:
    """리소스의 모든 알람 삭제 (레거시 + 새 포맷). 내부용."""
    cw = _get_cw_client()
    alarm_names = _find_alarms_for_resource(resource_id)
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
    return _delete_all_alarms_for_resource(resource_id)


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
    새 알람 포맷에서는 임계치가 이름에 포함되므로 변경 시 재생성 필요.

    Returns:
        {"created": [...], "updated": [...], "ok": [...]}
    """
    cw = _get_cw_client()
    alarm_defs = _get_alarm_defs(resource_type)
    result = {"created": [], "updated": [], "ok": []}

    # 현재 알람 목록 조회
    existing_alarms = _find_alarms_for_resource(resource_id)

    if not existing_alarms:
        # 알람이 하나도 없으면 전체 생성
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags)
        result["created"] = created
        return result

    # 기존 알람의 임계치 확인
    needs_recreate = False
    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]

        if alarm_def.get("dynamic_dimensions"):
            # Disk 알람: 기존 알람에서 disk_used_percent 관련 알람 찾기
            display = _METRIC_DISPLAY.get("Disk", ("disk_used_percent",))[0]
            disk_alarms = [a for a in existing_alarms if display in a]
            if not disk_alarms:
                needs_recreate = True
                continue
            # 임계치 확인
            try:
                resp = cw.describe_alarms(AlarmNames=disk_alarms)
                for alarm in resp.get("MetricAlarms", []):
                    name = alarm["AlarmName"]
                    existing_threshold = alarm.get("Threshold", 0)
                    disk_threshold = get_threshold(resource_tags, "Disk")
                    if abs(existing_threshold - disk_threshold) > 0.001:
                        needs_recreate = True
                        result["updated"].append(name)
                    else:
                        result["ok"].append(name)
            except ClientError as e:
                logger.error("Failed to check disk alarms for %s: %s", resource_id, e)
            continue

        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

        # 기존 알람에서 해당 메트릭 알람 찾기 (display name으로 검색)
        display = _METRIC_DISPLAY.get(metric, (metric,))[0]
        metric_alarms = [a for a in existing_alarms if display in a]
        if not metric_alarms:
            needs_recreate = True
            result["created"].append(metric)
            continue

        try:
            resp = cw.describe_alarms(AlarmNames=metric_alarms[:1])
            alarms = resp.get("MetricAlarms", [])
            if not alarms:
                needs_recreate = True
                result["created"].append(metric)
            else:
                existing_threshold = alarms[0].get("Threshold", 0)
                if abs(existing_threshold - cw_threshold) > 0.001:
                    needs_recreate = True
                    result["updated"].append(metric_alarms[0])
                else:
                    result["ok"].append(metric_alarms[0])
        except ClientError as e:
            logger.error("Failed to sync alarm for %s %s: %s", resource_id, metric, e)

    if needs_recreate:
        create_alarms_for_resource(resource_id, resource_type, resource_tags)

    return result
