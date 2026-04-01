"""
Daily_Monitor Lambda Handler

매일 1회 실행되어:
1. Monitoring=on 리소스의 CloudWatch Alarm 누락/불일치 점검 및 동기화
2. 메트릭 조회 → 임계치 비교 → SNS 알림 발송 (알람 보완)

단일 리소스 실패가 전체 실행을 중단시키지 않는 격리 패턴 적용.
"""

import functools
import logging
import re

import boto3

# Lambda 환경에서 root logger 레벨 설정 (모든 모듈에 적용)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from common.alarm_manager import sync_alarms_for_resource
from common.collectors import docdb as docdb_collector
from common.collectors import ec2 as ec2_collector
from common.collectors import elasticache as elasticache_collector
from common.collectors import elb as elb_collector
from common.collectors import natgw as natgw_collector
from common.collectors import rds as rds_collector
from common.collectors import lambda_fn as lambda_collector
from common.collectors import vpn as vpn_collector
from common.collectors import apigw as apigw_collector
from common.collectors import acm as acm_collector
from common.collectors import backup as backup_collector
from common.collectors import mq as mq_collector
from common.collectors import clb as clb_collector
from common.collectors import opensearch as opensearch_collector
from common.sns_notifier import send_alert, send_error_alert
from common.tag_resolver import get_threshold

# collector 모듈 목록 (런타임에 .get_metrics 참조하여 패치 가능하도록)
_COLLECTOR_MODULES = [
    ec2_collector, rds_collector, elb_collector, docdb_collector,
    elasticache_collector, natgw_collector,
    lambda_collector, vpn_collector, apigw_collector, acm_collector,
    backup_collector, mq_collector, clb_collector, opensearch_collector,
]

# 새 포맷 알람에서 resource_type과 resource_id를 추출하는 정규식
# 예: "[EC2] MyServer CPU >=80% (i-1234567890abcdef0)"
_NEW_FORMAT_RE = re.compile(r"^\[(\w+)\]\s.*\(TagName:\s(.+)\)$")

# resource_type → collector 모듈 매핑 (고아 알람 정리용)
_RESOURCE_TYPE_TO_COLLECTOR = {
    "EC2": ec2_collector,
    "RDS": rds_collector,
    "AuroraRDS": rds_collector,
    "DocDB": docdb_collector,
    "ELB": elb_collector,
    "ALB": elb_collector,
    "NLB": elb_collector,
    "TG": elb_collector,
    "ElastiCache": elasticache_collector,
    "NAT": natgw_collector,
    "NATGateway": natgw_collector,
    "Lambda": lambda_collector,
    "VPN": vpn_collector,
    "APIGW": apigw_collector,
    "ACM": acm_collector,
    "Backup": backup_collector,
    "MQ": mq_collector,
    "CLB": clb_collector,
    "OpenSearch": opensearch_collector,
}


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (거버넌스 §1)
# ──────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


def lambda_handler(event, context):
    """
    Lambda 핸들러 진입점.

    0단계: 고아 알람 정리 (terminated 인스턴스 알람 삭제)
    1단계: 알람 동기화 (누락/불일치 점검)
    2단계: 메트릭 조회 → 임계치 비교 → 알림 발송

    Returns:
        {"status": "ok", "processed": N, "alerts": M, "alarms_synced": {...}}
    """
    # 0단계: 고아 알람 정리
    try:
        orphaned = _cleanup_orphan_alarms()
        if orphaned:
            logger.info("Cleaned up orphan alarms: %s", orphaned)
    except Exception as e:
        logger.error("Failed to cleanup orphan alarms: %s", e)
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


# ──────────────────────────────────────────────
# 고아 알람 정리 (거버넌스 §3: 헬퍼 분리)
# ──────────────────────────────────────────────


def _collect_alarm_resource_ids(
) -> dict[str, dict[str, list[str]]]:
    """모든 알람에서 resource_type별 resource_id → 알람 이름 매핑 추출.

    새 포맷: [EC2] ... (resource_id) → resource_type, resource_id 추출
    레거시 포맷: i-xxx-metric-env → EC2, instance_id 추출

    Returns:
        {"EC2": {"i-xxx": ["alarm1", ...]}, "RDS": {...}, "ELB": {...}, "TG": {...}}
    """
    cw = _get_cw_client()
    result: dict[str, dict[str, list[str]]] = {}
    paginator = cw.get_paginator("describe_alarms")

    for page in paginator.paginate(AlarmTypes=["MetricAlarm"]):
        for alarm in page.get("MetricAlarms", []):
            name = alarm["AlarmName"]
            _classify_alarm(name, result)

    return result


def _classify_alarm(
    name: str,
    result: dict[str, dict[str, list[str]]],
) -> None:
    """단일 알람 이름을 분류하여 result에 추가."""
    # 새 포맷: [EC2] ... (resource_id)
    m = _NEW_FORMAT_RE.match(name)
    if m:
        rtype = m.group(1)
        rid = m.group(2)
        result.setdefault(rtype, {}).setdefault(rid, []).append(name)
        return

    # 레거시 포맷: i-xxx-metric-env
    legacy = re.match(r"^(i-[0-9a-f]+)-", name)
    if legacy:
        iid = legacy.group(1)
        result.setdefault("EC2", {}).setdefault(iid, []).append(name)


def _cleanup_orphan_alarms() -> list[str]:
    """
    존재하지 않는 리소스의 알람을 찾아 삭제.

    새 포맷 알람: [{resource_type}] ... ({resource_id}) — 괄호에서 resource_id 추출
    레거시 포맷 알람: i-xxx-metric-env — EC2 인스턴스 ID 추출

    Returns:
        삭제된 알람 이름 목록
    """
    alarm_map = _collect_alarm_resource_ids()
    if not alarm_map:
        return []

    to_delete: list[str] = []

    for rtype, id_to_alarms in alarm_map.items():
        collector = _RESOURCE_TYPE_TO_COLLECTOR.get(rtype)
        if collector is None:
            logger.warning(
                "No collector for resource type %s, skipping orphan cleanup",
                rtype,
            )
            continue

        resource_ids = set(id_to_alarms.keys())
        alive = collector.resolve_alive_ids(resource_ids)

        for rid, alarm_names in id_to_alarms.items():
            if rid not in alive:
                to_delete.extend(alarm_names)
                logger.info(
                    "Orphan alarms for %s %s: %s", rtype, rid, alarm_names,
                )

    if not to_delete:
        return []

    cw = _get_cw_client()
    for i in range(0, len(to_delete), 100):
        cw.delete_alarms(AlarmNames=to_delete[i:i + 100])

    logger.info("Deleted %d orphan alarms", len(to_delete))
    return to_delete


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
    elif resource_type == "AuroraRDS":
        metrics = collector_mod.get_aurora_metrics(resource_id, resource_tags)
    else:
        metrics = collector_mod.get_metrics(resource_id, resource_tags)

    if metrics is None:
        logger.info(
            "No metric data for %s (%s): skipping", resource_id, resource_type
        )
        return 0

    name_tag = resource_tags.get("Name", "")
    alerts_sent = 0
    for metric_name, current_value in metrics.items():
        threshold = get_threshold(resource_tags, metric_name)

        # FreeMemoryGB / FreeStorageGB / FreeLocalStorageGB는 값이 임계치 미만일 때 알림 (낮을수록 위험)
        if metric_name in ("FreeMemoryGB", "FreeStorageGB", "FreeLocalStorageGB",
                          "TunnelState", "DaysToExpiry", "OSFreeStorageSpace"):
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
                tag_name=name_tag,
            )
            alerts_sent += 1
        else:
            logger.debug(
                "OK: %s %s %s=%.2f (threshold=%.2f)",
                resource_type, resource_id, metric_name, current_value, threshold,
            )
    return alerts_sent
