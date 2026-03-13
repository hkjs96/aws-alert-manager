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


def _cleanup_orphan_alarms() -> list[str]:
    """
    존재하지 않는 EC2 인스턴스의 알람을 찾아 삭제.

    알람 이름 패턴: {instance_id}-{metric}-{env}
    i- 로 시작하는 알람에서 인스턴스 ID 추출 후 EC2 존재 여부 확인.

    Returns:
        삭제된 알람 이름 목록
    """
    import boto3
    from botocore.exceptions import ClientError

    cw = boto3.client("cloudwatch")
    ec2 = boto3.client("ec2")

    # 모든 알람 조회 (페이지네이션)
    alarm_names = []
    paginator = cw.get_paginator("describe_alarms")
    for page in paginator.paginate(AlarmTypes=["MetricAlarm"]):
        for alarm in page.get("MetricAlarms", []):
            name = alarm["AlarmName"]
            # i-로 시작하는 알람만 대상
            if name.startswith("i-"):
                alarm_names.append(name)

    if not alarm_names:
        return []

    # 알람 이름에서 인스턴스 ID 추출 (i-xxxxxxxxxxxxxxxxx 패턴)
    import re
    instance_ids = set()
    alarm_by_instance: dict[str, list[str]] = {}
    for name in alarm_names:
        m = re.match(r"^(i-[0-9a-f]+)-", name)
        if m:
            iid = m.group(1)
            instance_ids.add(iid)
            alarm_by_instance.setdefault(iid, []).append(name)

    if not instance_ids:
        return []

    # EC2 존재 여부 확인 (terminated/없는 인스턴스 찾기)
    alive = set()
    # 최대 1000개씩 배치 처리
    id_list = list(instance_ids)
    for i in range(0, len(id_list), 200):
        batch = id_list[i:i+200]
        try:
            resp = ec2.describe_instances(InstanceIds=batch)
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    state = inst.get("State", {}).get("Name", "")
                    if state not in ("terminated", "shutting-down"):
                        alive.add(inst["InstanceId"])
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "InvalidInstanceID.NotFound":
                # 일부 ID가 완전히 없음 - 개별 확인
                for iid in batch:
                    try:
                        r2 = ec2.describe_instances(InstanceIds=[iid])
                        for res in r2.get("Reservations", []):
                            for inst in res.get("Instances", []):
                                state = inst.get("State", {}).get("Name", "")
                                if state not in ("terminated", "shutting-down"):
                                    alive.add(inst["InstanceId"])
                    except ClientError:
                        pass  # 완전히 없는 인스턴스 → alive에 추가 안 함
            else:
                logger.error("describe_instances failed: %s", e)
                return []

    # 존재하지 않거나 terminated된 인스턴스의 알람 삭제
    to_delete = []
    for iid in instance_ids:
        if iid not in alive:
            to_delete.extend(alarm_by_instance[iid])

    if not to_delete:
        return []

    # CloudWatch delete_alarms는 최대 100개씩
    for i in range(0, len(to_delete), 100):
        cw.delete_alarms(AlarmNames=to_delete[i:i+100])
    logger.info("Deleted orphan alarms for non-existent instances: %s", to_delete)
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
                tag_name=name_tag,
            )
            alerts_sent += 1
        else:
            logger.debug(
                "OK: %s %s %s=%.2f (threshold=%.2f)",
                resource_type, resource_id, metric_name, current_value, threshold,
            )
    return alerts_sent
