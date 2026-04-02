"""
SNS_Notifier 모듈 - Requirements 3.1, 3.2, 3.4, 5.2, 8.2, 8.5

Amazon SNS를 통해 알림 메시지를 발송하는 모듈.
모든 함수는 SNS 발송 실패 시 CloudWatch Logs에 기록하고 예외를 삼킨다.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


def _get_sns_client():
    return boto3.client("sns")


# 알림 유형별 환경변수 → 기본값(SNS_TOPIC_ARN) 순으로 폴백
_TOPIC_ARN_ENV_MAP = {
    "THRESHOLD_EXCEEDED": "SNS_TOPIC_ARN_ALERT",
    "REMEDIATION_PERFORMED": "SNS_TOPIC_ARN_REMEDIATION",
    "RESOURCE_DELETED": "SNS_TOPIC_ARN_LIFECYCLE",
    "MONITORING_REMOVED": "SNS_TOPIC_ARN_LIFECYCLE",
    "ERROR": "SNS_TOPIC_ARN_ERROR",
}


def _get_topic_arn(alert_type: str = "") -> str:
    """
    알림 유형별 SNS 토픽 ARN 조회.
    우선순위: 유형별 환경변수 → SNS_TOPIC_ARN (기본값 폴백)
    """
    specific_env = _TOPIC_ARN_ENV_MAP.get(alert_type, "")
    if specific_env:
        arn = os.environ.get(specific_env, "")
        if arn:
            return arn
    return os.environ.get("SNS_TOPIC_ARN", "")


def _publish(message: dict) -> None:
    """SNS 토픽에 JSON 메시지 발송. 실패 시 로그만 기록하고 예외를 삼킨다."""
    alert_type = message.get("alert_type", "")
    topic_arn = _get_topic_arn(alert_type)
    if not topic_arn:
        logger.error(
            "No SNS topic ARN configured for alert_type=%r "
            "(set SNS_TOPIC_ARN_%s or SNS_TOPIC_ARN)",
            alert_type,
            _TOPIC_ARN_ENV_MAP.get(alert_type, ""),
        )
        return
    try:
        body = json.dumps(message, ensure_ascii=False)
        _get_sns_client().publish(
            TopicArn=topic_arn,
            Message=body,
            Subject=alert_type or "ALERT",
        )
    except Exception as e:
        logger.error("SNS publish failed: %s | message=%s", e, message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _format_tag_name(tag_name: str | None) -> str:
    """tag_name이 truthy이면 그대로 반환, 아니면 'N/A' 반환."""
    return tag_name if tag_name else "N/A"



# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def send_alert(
    resource_id: str,
    resource_type: str,
    metric_name: str,
    current_value: float,
    threshold: float,
    tag_name: str = "",
) -> None:
    """
    임계치 초과 알림 발송 - Requirements 3.1, 3.2

    Args:
        resource_id: 리소스 ID
        resource_type: 리소스 유형 ('EC2' | 'RDS' | 'ELB')
        metric_name: 메트릭 이름
        current_value: 현재 메트릭 값
        threshold: 임계치 값
        tag_name: 리소스 Name 태그 값 (빈 문자열이면 N/A로 표시)
    """
    formatted = _format_tag_name(tag_name)
    message = {
        "alert_type": "THRESHOLD_EXCEEDED",
        "resource_id": resource_id,
        "resource_type": resource_type,
        "metric_name": metric_name,
        "current_value": current_value,
        "threshold": threshold,
        "tag_name": formatted,
        "timestamp": _now_iso(),
        "message": (
            f"[{resource_type}] {resource_id} (TagName: {formatted}) - {metric_name} "
            f"exceeded threshold: {current_value} > {threshold}"
        ),
    }
    _publish(message)


def send_remediation_alert(
    resource_id: str,
    resource_type: str,
    change_summary: str,
    action_taken: str,
    tag_name: str = "",
) -> None:
    """
    Auto-Remediation 완료 알림 발송 - Requirements 5.2

    Args:
        resource_id: 리소스 ID
        resource_type: 리소스 유형
        change_summary: 감지된 변경 내용 요약
        action_taken: 수행된 조치 ('STOPPED' | 'DELETED')
        tag_name: 리소스 Name 태그 값 (빈 문자열이면 N/A로 표시)
    """
    formatted = _format_tag_name(tag_name)
    message = {
        "alert_type": "REMEDIATION_PERFORMED",
        "resource_id": resource_id,
        "resource_type": resource_type,
        "change_summary": change_summary,
        "action_taken": action_taken,
        "tag_name": formatted,
        "timestamp": _now_iso(),
        "message": (
            f"[{resource_type}] {resource_id} (TagName: {formatted}) - unauthorized change detected. "
            f"Change: {change_summary}. Action: {action_taken}"
        ),
    }
    _publish(message)


def send_lifecycle_alert(
    resource_id: str,
    resource_type: str,
    event_type: str,
    message_text: str,
    tag_name: str = "",
) -> None:
    """
    리소스 생명주기 변경 알림 발송 - Requirements 8.2, 8.5

    Args:
        resource_id: 리소스 ID
        resource_type: 리소스 유형
        event_type: 이벤트 유형 ('RESOURCE_DELETED' | 'MONITORING_REMOVED')
        message_text: 사람이 읽을 수 있는 요약
        tag_name: 리소스 Name 태그 값 (빈 문자열이면 N/A로 표시)
    """
    formatted = _format_tag_name(tag_name)
    message = {
        "alert_type": event_type,
        "resource_id": resource_id,
        "resource_type": resource_type,
        "tag_name": formatted,
        "message": f"{message_text} (TagName: {formatted})",
        "timestamp": _now_iso(),
    }
    _publish(message)


def send_error_alert(context: str, error: Exception) -> None:
    """
    운영 오류 알림 발송 - Requirements 1.4, 4.4, 5.3

    Args:
        context: 오류 발생 컨텍스트 설명
        error: 발생한 예외
    """
    message = {
        "alert_type": "ERROR",
        "context": context,
        "error": str(error),
        "error_type": type(error).__name__,
        "timestamp": _now_iso(),
        "message": f"Operational error in {context}: {error}",
    }
    _publish(message)
