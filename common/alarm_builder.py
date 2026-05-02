"""
Alarm Builder — 알람 생성 로직

CloudWatch put_metric_alarm 호출을 담당하는 알람 생성 전담 모듈.
표준/Disk/동적 알람 생성 및 재생성 로직을 포함한다.
"""

import functools
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

import common._clients as _clients
from common.alarm_naming import (
    _build_alarm_description,
    _parse_alarm_metadata,
    _pretty_alarm_name,
    _shorten_elb_resource_id,
)
from common.alarm_registry import (
    _get_alarm_defs,
    get_severity,
)
from common.dimension_builder import (
    _build_dimensions,
    _get_disk_dimensions,
    _resolve_metric_dimensions,
    _resolve_tg_namespace,
)
from common.tag_resolver import (
    disk_path_to_tag_suffix,
    get_threshold,
    is_threshold_off,
    tag_suffix_to_disk_path,
)
from common.threshold_resolver import (
    _resolve_free_local_storage_threshold,
    _resolve_free_memory_threshold,
    resolve_threshold,
)

logger = logging.getLogger("common.alarm_manager")


def _get_sns_alert_arn() -> str:
    return os.environ.get("SNS_TOPIC_ARN_ALERT", "")


def _get_global_sns_arn() -> str:
    """us-east-1 글로벌 서비스 알람용 SNS ARN. 미설정 시 빈 문자열(AlarmActions 비움)."""
    return os.environ.get("SNS_TOPIC_ARN_GLOBAL_ALERT", "")


# ──────────────────────────────────────────────
# Severity 태그 부여 (Phase2 §13-4)
# ──────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _get_aws_account_id() -> str:
    """현재 AWS 계정 ID (lru_cache — Lambda 컨테이너 생애주기 동안 1회만 STS 호출)."""
    return boto3.client("sts").get_caller_identity()["Account"]


def _tag_alarm_with_severity(alarm_name: str, metric_key: str, cw) -> None:
    """알람 생성 직후 Severity + ManagedBy 태그를 부여한다.

    tag_resource 실패는 알람 생성 성공에 영향을 주지 않도록 예외를 흡수한다.
    BotoCoreError: NoCredentialsError 등 자격증명 문제 포함.
    """
    severity = get_severity(metric_key)
    try:
        region = cw.meta.region_name
        account_id = _get_aws_account_id()
        alarm_arn = f"arn:aws:cloudwatch:{region}:{account_id}:alarm:{alarm_name}"
        cw.tag_resource(
            ResourceARN=alarm_arn,
            Tags=[
                {"Key": "Severity", "Value": severity},
                {"Key": "ManagedBy", "Value": "AlarmManager"},
            ],
        )
    except (ClientError, BotoCoreError) as e:
        logger.warning("Failed to tag alarm %s with severity: %s", alarm_name, e)


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
            "Skipping disk_used_percent alarm for %s: no CWAgent metrics found. "
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
            _tag_alarm_with_severity(name, alarm_metric, cw)
        except ClientError as e:
            logger.error("Failed to create disk alarm %s: %s", name, e)
    return created


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
    metric_key = alarm_def.get("metric_key") or metric

    # region 필드가 있으면 해당 리전의 CloudWatch 클라이언트 사용
    region = alarm_def.get("region")
    if region:
        cw = _clients._get_cw_client_for_region(region)
        # 글로벌 서비스 알람: us-east-1 전용 SNS ARN 사용 (미설정 시 AlarmActions 비움)
        sns_arn = _get_global_sns_arn()

    threshold, cw_threshold = resolve_threshold(alarm_def, resource_tags)

    dimensions = _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)

    namespace = (
        _resolve_tg_namespace(alarm_def, resource_tags)
        if resource_type == "TG"
        else alarm_def["namespace"]
    )

    name = _pretty_alarm_name(
        resource_type, resource_id, resource_name,
        metric_key, threshold, resource_tags,
    )
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
            TreatMissingData=alarm_def.get("treat_missing_data", "missing"),
        )
        logger.info("Created alarm: %s (threshold=%.2f)", name, threshold)
        _tag_alarm_with_severity(name, alarm_def.get("metric_key") or alarm_def["metric"], cw)
        return name
    except ClientError as e:
        logger.error("Failed to create alarm %s: %s", name, e)
        return None


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
    resource_tags: dict | None = None,
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
    threshold_part = f" {direction} {thr_str} "
    short_id = _shorten_elb_resource_id(resource_id, resource_type, resource_tags)
    suffix = f"(TagName: {short_id})"
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
        _tag_alarm_with_severity(name, metric_name, cw)
        logger.info(
            "Created dynamic alarm: %s (metric=%s, threshold=%.2f, comparison=%s)",
            name, metric_name, threshold, comparison,
        )
        created.append(name)
    except ClientError as e:
        logger.error(
            "Failed to create dynamic alarm %s: %s", name, e,
        )


# ──────────────────────────────────────────────
# 개별 알람 재생성 헬퍼
# ──────────────────────────────────────────────


# 이전 내부 메트릭 키 → 새 CloudWatch 기반 메트릭 키 변환 (기배포 알람 AlarmDescription 호환)
_LEGACY_KEY_MAP: dict[str, str] = {
    "CPU": "CPUUtilization",
    "Memory": "mem_used_percent",
    "Disk": "disk_used_percent",
    "FreeMemoryGB": "FreeableMemory",
    "FreeStorageGB": "FreeStorageSpace",
    "Connections": "DatabaseConnections",
    "ELB5XX": "HTTPCode_ELB_5XX_Count",
    "TCPClientReset": "TCP_Client_Reset_Count",
    "TCPTargetReset": "TCP_Target_Reset_Count",
    "TGResponseTime": "TargetResponseTime",
}


def _resolve_metric_key(alarm_info: dict) -> str:
    """알람 정보에서 메트릭 키를 해석 (메타데이터 우선, 폴백으로 MetricName)."""
    desc = alarm_info.get("AlarmDescription", "")
    metadata = _parse_alarm_metadata(desc)
    if metadata and "metric_key" in metadata:
        return metadata["metric_key"]
    metric_name = alarm_info.get("MetricName", "")
    # 레거시 디스크 알람: MetricName=disk_used_percent → Disk_{suffix} 변환
    if metric_name == "disk_used_percent":
        path = next(
            (d["Value"] for d in alarm_info.get("Dimensions", []) if d["Name"] == "path"),
            "",
        )
        suffix = disk_path_to_tag_suffix(path) if path else "root"
        return f"Disk_{suffix}"
    return metric_name


def _create_single_alarm(
    metric: str,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    *,
    cw=None,
) -> None:
    """전체 삭제 없이 단일 메트릭 알람만 생성 (result["created"] 처리용)."""
    cw = cw or _clients._get_cw_client()
    sns_arn = _get_sns_alert_arn()
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    resource_name = resource_tags.get("Name", "")

    alarm_def = next((d for d in alarm_defs if d["metric"] == metric), None)
    if alarm_def is None:
        logger.warning("No alarm definition found for metric %s", metric)
        return

    # region 필드가 있으면 해당 리전의 CloudWatch 클라이언트 사용
    region = alarm_def.get("region")
    if region:
        cw = _clients._get_cw_client_for_region(region)
        sns_arn = _get_global_sns_arn()

    threshold, cw_threshold = resolve_threshold(alarm_def, resource_tags)

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
            TreatMissingData=alarm_def.get("treat_missing_data", "missing"),
        )
        logger.info("Created single alarm: %s (threshold=%.2f)", name, threshold)
        _tag_alarm_with_severity(name, metric, cw)
    except ClientError as e:
        logger.error("Failed to create single alarm %s: %s", name, e)


def _recreate_alarm_by_name(
    alarm_name: str,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    *,
    cw=None,
) -> None:
    """알람 이름에서 메트릭 타입을 파악하여 해당 알람만 삭제 후 재생성.

    Disk 알람의 경우 기존 Dimensions(path, device, fstype 등)를 재사용한다.
    """
    cw = cw or _clients._get_cw_client()
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
    alarm_def = next(
        (d for d in alarm_defs if (d.get("metric_key") or d["metric"]) == metric_key),
        None,
    )
    if alarm_def is None:
        logger.warning(
            "No alarm definition found for metric key %s (alarm: %s)",
            metric_key, alarm_name,
        )
        return

    if metric_key.startswith("Disk_"):
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
    disk_metric_label = f"disk_used_percent-{path.lstrip('/') or 'root'}"
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
    # region 필드가 있으면 해당 리전의 CloudWatch 클라이언트 사용
    region = alarm_def.get("region")
    if region:
        cw = _clients._get_cw_client_for_region(region)

    threshold, cw_threshold = resolve_threshold(alarm_def, resource_tags)

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
            TreatMissingData=alarm_def.get("treat_missing_data", "missing"),
        )
        logger.info("Recreated alarm: %s (threshold=%.2f)", name, threshold)
    except ClientError as e:
        logger.error("Failed to recreate alarm %s: %s", name, e)
