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

from common import HARDCODED_DEFAULTS
from common.tag_resolver import get_threshold, get_disk_thresholds

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
    """알람 이름 생성: {resource_id}-{metric}-{env}"""
    return f"{resource_id}-{metric}-{_get_env()}"


# ──────────────────────────────────────────────
# 리소스 유형별 알람 정의
# ──────────────────────────────────────────────

# EC2 기본 알람 (CWAgent 메트릭은 태그 기반으로 추가)
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

        name = _alarm_name(resource_id, metric)

        try:
            cw.put_metric_alarm(
                AlarmName=name,
                AlarmDescription=f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
                Namespace=alarm_def["namespace"],
                MetricName=alarm_def["metric_name"],
                Dimensions=[{
                    "Name": alarm_def["dimension_key"],
                    "Value": dim_value,
                }],
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


# ──────────────────────────────────────────────
# 알람 삭제
# ──────────────────────────────────────────────

def delete_alarms_for_resource(
    resource_id: str,
    resource_type: str,
) -> list[str]:
    """
    리소스에 대한 CloudWatch Alarm을 삭제한다.

    Returns:
        삭제된 알람 이름 목록
    """
    cw = _get_cw_client()
    alarm_defs = _get_alarm_defs(resource_type)
    deleted = []

    alarm_names = [_alarm_name(resource_id, d["metric"]) for d in alarm_defs]

    if not alarm_names:
        return deleted

    try:
        cw.delete_alarms(AlarmNames=alarm_names)
        logger.info("Deleted alarms: %s", alarm_names)
        deleted = alarm_names
    except ClientError as e:
        logger.error("Failed to delete alarms for %s: %s", resource_id, e)

    return deleted


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

    Returns:
        {"created": [...], "updated": [...], "ok": [...]}
    """
    cw = _get_cw_client()
    alarm_defs = _get_alarm_defs(resource_type)
    result = {"created": [], "updated": [], "ok": []}

    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        name = _alarm_name(resource_id, metric)
        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

        try:
            resp = cw.describe_alarms(AlarmNames=[name])
            alarms = resp.get("MetricAlarms", [])

            if not alarms:
                # 알람 누락 → 생성
                create_alarms_for_resource(resource_id, resource_type, resource_tags)
                result["created"].append(name)
            else:
                existing = alarms[0]
                existing_threshold = existing.get("Threshold", 0)
                # 임계치 불일치 → 업데이트 (재생성)
                if abs(existing_threshold - cw_threshold) > 0.001:
                    logger.info(
                        "Alarm %s threshold mismatch: existing=%.2f expected=%.2f, updating",
                        name, existing_threshold, cw_threshold,
                    )
                    create_alarms_for_resource(resource_id, resource_type, resource_tags)
                    result["updated"].append(name)
                else:
                    result["ok"].append(name)
        except ClientError as e:
            logger.error("Failed to sync alarm %s: %s", name, e)

    return result
