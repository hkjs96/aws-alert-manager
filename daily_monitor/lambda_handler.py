"""
Daily_Monitor Lambda Handler

매일 1회 실행되어:
1. Monitoring=on 리소스의 CloudWatch Alarm 누락/불일치 점검 및 동기화
2. 메트릭 조회 → 임계치 비교 → SNS 알림 발송 (알람 보완)

단일 리소스 실패가 전체 실행을 중단시키지 않는 격리 패턴 적용.
"""

import logging

# Lambda 환경에서 root logger 레벨 설정 (모든 모듈에 적용)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from common.alarm_manager import sync_alarms_for_resource
from common.collectors import ec2 as ec2_collector
from common.collectors import elb as elb_collector
from common.collectors import rds as rds_collector
from common.sns_notifier import send_alert, send_error_alert
from common.tag_resolver import get_threshold

# collector 모듈 목록 (런타임에 .get_metrics 참조하여 패치 가능하도록)
_COLLECTOR_MODULES = [ec2_collector, rds_collector, elb_collector]


def lambda_handler(event, context):
    """
    Lambda 핸들러 진입점.

    1단계: 알람 동기화 (누락/불일치 점검)
    2단계: 메트릭 조회 → 임계치 비교 → 알림 발송

    Returns:
        {"status": "ok", "processed": N, "alerts": M, "alarms_synced": {...}}
    """
    total_processed = 0
    total_alerts = 0
    alarms_synced = {"created": 0, "updated": 0, "ok": 0}

    for collector_mod in _COLLECTOR_MODULES:
        try:
            resources = collector_mod.collect_monitored_resources()
        except Exception as e:
            logger.error(
                "Failed to collect resources from %s: %s",
                collector_mod.__name__, e,
            )
            send_error_alert(
                context=f"collect_monitored_resources [{collector_mod.__name__}]",
                error=e,
            )
            continue

        if not resources:
            logger.info("No monitored resources found in %s", collector_mod.__name__)
            continue

        for resource in resources:
            resource_id = resource["id"]
            resource_type = resource["type"]
            resource_tags = resource.get("tags", {})

            # 1단계: 알람 동기화
            try:
                sync_result = sync_alarms_for_resource(
                    resource_id, resource_type, resource_tags,
                )
                alarms_synced["created"] += len(sync_result.get("created", []))
                alarms_synced["updated"] += len(sync_result.get("updated", []))
                alarms_synced["ok"] += len(sync_result.get("ok", []))
            except Exception as e:
                logger.error(
                    "Failed to sync alarms for %s (%s): %s",
                    resource_id, resource_type, e,
                )

            # 2단계: 메트릭 조회 + 임계치 비교
            try:
                alerts = _process_resource(
                    resource_id, resource_type, resource_tags, collector_mod
                )
                total_processed += 1
                total_alerts += alerts
            except Exception as e:
                logger.error(
                    "Unexpected error processing resource %s (%s): %s",
                    resource_id, resource_type, e,
                )
                send_error_alert(
                    context=f"process_resource {resource_id} ({resource_type})",
                    error=e,
                )

    logger.info(
        "Daily monitor complete: processed=%d, alerts=%d, alarms_synced=%s",
        total_processed, total_alerts, alarms_synced,
    )
    return {
        "status": "ok",
        "processed": total_processed,
        "alerts": total_alerts,
        "alarms_synced": alarms_synced,
    }


def _process_resource(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    collector_mod,
) -> int:
    """
    단일 리소스 메트릭 조회 및 임계치 비교.

    Returns:
        발송된 알림 수
    """
    # ELB TG의 경우 lb_arn 태그 전달
    if resource_type == "TG":
        lb_arn = resource_tags.get("_lb_arn")
        metrics = collector_mod.get_metrics(resource_id, resource_tags, lb_arn=lb_arn)
    else:
        metrics = collector_mod.get_metrics(resource_id, resource_tags)

    if metrics is None:
        logger.info(
            "No metric data for %s (%s): skipping", resource_id, resource_type
        )
        return 0

    alerts_sent = 0
    for metric_name, current_value in metrics.items():
        threshold = get_threshold(resource_tags, metric_name)

        # FreeMemoryGB / FreeStorageGB는 값이 임계치 미만일 때 알림 (낮을수록 위험)
        if metric_name in ("FreeMemoryGB", "FreeStorageGB"):
            exceeded = current_value < threshold
        else:
            exceeded = current_value > threshold

        if exceeded:
            logger.warning(
                "Threshold exceeded: %s %s %s=%.2f (threshold=%.2f)",
                resource_type, resource_id, metric_name, current_value, threshold,
            )
            send_alert(
                resource_id=resource_id,
                resource_type=resource_type,
                metric_name=metric_name,
                current_value=current_value,
                threshold=threshold,
            )
            alerts_sent += 1
        else:
            logger.debug(
                "OK: %s %s %s=%.2f (threshold=%.2f)",
                resource_type, resource_id, metric_name, current_value, threshold,
            )
    return alerts_sent
