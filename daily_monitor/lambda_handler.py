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
from botocore.exceptions import ClientError

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


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (거버넌스 §1)
# ──────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2")


@functools.lru_cache(maxsize=None)
def _get_rds_client():
    return boto3.client("rds")


@functools.lru_cache(maxsize=None)
def _get_elb_client():
    return boto3.client("elbv2")


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


def _find_alive_ec2_instances(instance_ids: set[str]) -> set[str]:
    """EC2 인스턴스 존재 여부 확인. terminated/shutting-down 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    id_list = list(instance_ids)

    for i in range(0, len(id_list), 200):
        batch = id_list[i:i + 200]
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
                _check_ec2_individually(batch, alive)
            else:
                logger.error("describe_instances failed: %s", e)

    return alive


def _check_ec2_individually(
    batch: list[str], alive: set[str],
) -> None:
    """배치 조회 실패 시 개별 인스턴스 확인."""
    ec2 = _get_ec2_client()
    for iid in batch:
        try:
            resp = ec2.describe_instances(InstanceIds=[iid])
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    state = inst.get("State", {}).get("Name", "")
                    if state not in ("terminated", "shutting-down"):
                        alive.add(inst["InstanceId"])
        except ClientError:
            pass  # 완전히 없는 인스턴스 → alive에 추가 안 함


def _find_alive_rds_instances(db_ids: set[str]) -> set[str]:
    """RDS DB 인스턴스 존재 여부 확인."""
    rds = _get_rds_client()
    alive: set[str] = set()

    for db_id in db_ids:
        try:
            rds.describe_db_instances(DBInstanceIdentifier=db_id)
            alive.add(db_id)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "DBInstanceNotFound":
                logger.info("RDS instance not found (orphan): %s", db_id)
            else:
                logger.error(
                    "describe_db_instances failed for %s: %s", db_id, e,
                )

    return alive


def _find_alive_elb_resources(resource_ids: set[str]) -> set[str]:
    """ELB/TG 리소스 존재 여부 확인.

    resource_id가 ARN 형식이면 직접 조회, 아니면 skip.
    ELB: describe_load_balancers(LoadBalancerArns=[...])
    TG: describe_target_groups(TargetGroupArns=[...])
    """
    elb_client = _get_elb_client()
    alive: set[str] = set()

    lb_arns = [r for r in resource_ids if ":loadbalancer/" in r]
    tg_arns = [r for r in resource_ids if ":targetgroup/" in r]
    other_ids = resource_ids - set(lb_arns) - set(tg_arns)

    # ELB ARN 조회
    if lb_arns:
        _check_elb_arns(elb_client, lb_arns, alive)

    # TG ARN 조회
    if tg_arns:
        _check_tg_arns(elb_client, tg_arns, alive)

    # ARN이 아닌 ID (예: app/my-lb/xxx 형식) — 존재 확인 불가, 보수적으로 alive 처리
    alive.update(other_ids)

    return alive


def _check_elb_arns(
    elb_client, lb_arns: list[str], alive: set[str],
) -> None:
    """ELB LoadBalancer ARN 존재 확인."""
    for arn in lb_arns:
        try:
            elb_client.describe_load_balancers(LoadBalancerArns=[arn])
            alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "LoadBalancerNotFound":
                logger.info("ELB not found (orphan): %s", arn)
            else:
                logger.error(
                    "describe_load_balancers failed for %s: %s", arn, e,
                )


def _check_tg_arns(
    elb_client, tg_arns: list[str], alive: set[str],
) -> None:
    """TargetGroup ARN 존재 확인."""
    for arn in tg_arns:
        try:
            elb_client.describe_target_groups(TargetGroupArns=[arn])
            alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "TargetGroupNotFound":
                logger.info("TG not found (orphan): %s", arn)
            else:
                logger.error(
                    "describe_target_groups failed for %s: %s", arn, e,
                )


@functools.lru_cache(maxsize=None)
def _get_elasticache_client():
    return boto3.client("elasticache")


def _find_alive_elasticache_clusters(cluster_ids: set[str]) -> set[str]:
    """ElastiCache 클러스터 존재 여부 확인."""
    client = _get_elasticache_client()
    alive: set[str] = set()
    for cid in cluster_ids:
        try:
            client.describe_cache_clusters(CacheClusterId=cid)
            alive.add(cid)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "CacheClusterNotFound":
                logger.info("ElastiCache cluster not found (orphan): %s", cid)
            else:
                logger.error("describe_cache_clusters failed for %s: %s", cid, e)
    return alive


def _find_alive_nat_gateways(natgw_ids: set[str]) -> set[str]:
    """NAT Gateway 존재 여부 확인. deleting/deleted 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    id_list = list(natgw_ids)
    for i in range(0, len(id_list), 200):
        batch = id_list[i:i + 200]
        try:
            resp = ec2.describe_nat_gateways(NatGatewayIds=batch)
            for natgw in resp.get("NatGateways", []):
                state = natgw.get("State", "")
                if state not in ("deleted", "deleting"):
                    alive.add(natgw["NatGatewayId"])
        except ClientError as e:
            logger.error("describe_nat_gateways failed: %s", e)
    return alive


# ──────────────────────────────────────────────
# 신규 리소스 alive checkers (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_lambda_client():
    return boto3.client("lambda")


@functools.lru_cache(maxsize=None)
def _get_backup_client():
    return boto3.client("backup")


@functools.lru_cache(maxsize=None)
def _get_mq_client():
    return boto3.client("mq")


@functools.lru_cache(maxsize=None)
def _get_classic_elb_client():
    return boto3.client("elb")


@functools.lru_cache(maxsize=None)
def _get_opensearch_client():
    return boto3.client("opensearch")


@functools.lru_cache(maxsize=None)
def _get_acm_client():
    return boto3.client("acm")


@functools.lru_cache(maxsize=None)
def _get_apigw_client():
    return boto3.client("apigateway")


@functools.lru_cache(maxsize=None)
def _get_apigwv2_client():
    return boto3.client("apigatewayv2")


def _find_alive_lambda_functions(fn_names: set[str]) -> set[str]:
    """Lambda 함수 존재 여부 확인."""
    client = _get_lambda_client()
    alive: set[str] = set()
    for name in fn_names:
        try:
            client.get_function(FunctionName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("Lambda function not found (orphan): %s", name)
            else:
                logger.error("get_function failed for %s: %s", name, e)
    return alive


def _find_alive_vpn_connections(vpn_ids: set[str]) -> set[str]:
    """VPN Connection 존재 여부 확인. deleted/deleting 제외."""
    ec2 = _get_ec2_client()
    alive: set[str] = set()
    try:
        resp = ec2.describe_vpn_connections(
            VpnConnectionIds=list(vpn_ids)
        )
        for vpn in resp.get("VpnConnections", []):
            state = vpn.get("State", "")
            if state not in ("deleted", "deleting"):
                alive.add(vpn["VpnConnectionId"])
    except ClientError as e:
        logger.error("describe_vpn_connections failed: %s", e)
    return alive


def _find_alive_apigw_apis(api_ids: set[str]) -> set[str]:
    """API Gateway (REST + v2) 존재 여부 확인."""
    alive: set[str] = set()
    # REST APIs (id = api_name, so check by listing)
    try:
        client = _get_apigw_client()
        paginator = client.get_paginator("get_rest_apis")
        for page in paginator.paginate():
            for api in page.get("items", []):
                if api.get("name", "") in api_ids:
                    alive.add(api["name"])
    except ClientError as e:
        logger.error("get_rest_apis failed: %s", e)
    # v2 APIs (id = api_id)
    try:
        v2 = _get_apigwv2_client()
        paginator = v2.get_paginator("get_apis")
        for page in paginator.paginate():
            for api in page.get("Items", []):
                if api["ApiId"] in api_ids:
                    alive.add(api["ApiId"])
    except ClientError as e:
        logger.error("get_apis (v2) failed: %s", e)
    return alive


def _find_alive_acm_certificates(cert_arns: set[str]) -> set[str]:
    """ACM 인증서 존재 여부 확인."""
    client = _get_acm_client()
    alive: set[str] = set()
    for arn in cert_arns:
        try:
            resp = client.describe_certificate(CertificateArn=arn)
            status = resp.get("Certificate", {}).get("Status", "")
            if status != "EXPIRED":
                alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("ACM cert not found (orphan): %s", arn)
            else:
                logger.error("describe_certificate failed for %s: %s", arn, e)
    return alive


def _find_alive_backup_vaults(vault_names: set[str]) -> set[str]:
    """Backup Vault 존재 여부 확인."""
    client = _get_backup_client()
    alive: set[str] = set()
    for name in vault_names:
        try:
            client.describe_backup_vault(BackupVaultName=name)
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.info("Backup vault not found (orphan): %s", name)
            else:
                logger.error("describe_backup_vault failed for %s: %s", name, e)
    return alive


def _find_alive_mq_brokers(broker_names: set[str]) -> set[str]:
    """MQ Broker 존재 여부 확인."""
    client = _get_mq_client()
    alive: set[str] = set()
    try:
        paginator = client.get_paginator("list_brokers")
        for page in paginator.paginate():
            for b in page.get("BrokerSummaries", []):
                if b["BrokerName"] in broker_names:
                    alive.add(b["BrokerName"])
    except ClientError as e:
        logger.error("list_brokers failed: %s", e)
    return alive


def _find_alive_clb_load_balancers(lb_names: set[str]) -> set[str]:
    """Classic Load Balancer 존재 여부 확인."""
    client = _get_classic_elb_client()
    alive: set[str] = set()
    for name in lb_names:
        try:
            client.describe_load_balancers(LoadBalancerNames=[name])
            alive.add(name)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "LoadBalancerNotFound":
                logger.info("CLB not found (orphan): %s", name)
            else:
                logger.error("describe_load_balancers failed for %s: %s", name, e)
    return alive


def _find_alive_opensearch_domains(domain_names: set[str]) -> set[str]:
    """OpenSearch 도메인 존재 여부 확인."""
    client = _get_opensearch_client()
    alive: set[str] = set()
    name_list = list(domain_names)
    for i in range(0, len(name_list), 5):
        batch = name_list[i:i + 5]
        try:
            resp = client.describe_domains(DomainNames=batch)
            for d in resp.get("DomainStatusList", []):
                if not d.get("Deleted", False):
                    alive.add(d["DomainName"])
        except ClientError as e:
            logger.error("describe_domains failed: %s", e)
    return alive


def _cleanup_orphan_alarms() -> list[str]:
    """
    존재하지 않는 리소스(EC2/RDS/ELB/TG)의 알람을 찾아 삭제.

    새 포맷 알람: [{resource_type}] ... ({resource_id}) — 괄호에서 resource_id 추출
    레거시 포맷 알람: i-xxx-metric-env — EC2 인스턴스 ID 추출

    Returns:
        삭제된 알람 이름 목록
    """
    alarm_map = _collect_alarm_resource_ids()
    if not alarm_map:
        return []

    to_delete: list[str] = []

    # resource_type별 존재 확인 함수 매핑
    alive_checkers = {
        "EC2": _find_alive_ec2_instances,
        "RDS": _find_alive_rds_instances,
        "AuroraRDS": _find_alive_rds_instances,
        "DocDB": _find_alive_rds_instances,
        "ELB": _find_alive_elb_resources,
        "ALB": _find_alive_elb_resources,
        "NLB": _find_alive_elb_resources,
        "TG": _find_alive_elb_resources,
        "ElastiCache": _find_alive_elasticache_clusters,
        "NAT": _find_alive_nat_gateways,
        "NATGateway": _find_alive_nat_gateways,  # legacy alias
        "Lambda": _find_alive_lambda_functions,
        "VPN": _find_alive_vpn_connections,
        "APIGW": _find_alive_apigw_apis,
        "ACM": _find_alive_acm_certificates,
        "Backup": _find_alive_backup_vaults,
        "MQ": _find_alive_mq_brokers,
        "CLB": _find_alive_clb_load_balancers,
        "OpenSearch": _find_alive_opensearch_domains,
    }

    for rtype, id_to_alarms in alarm_map.items():
        checker = alive_checkers.get(rtype)
        if checker is None:
            logger.warning(
                "No alive checker for resource type %s, skipping orphan cleanup",
                rtype,
            )
            continue

        resource_ids = set(id_to_alarms.keys())
        alive = checker(resource_ids)

        for rid, alarm_names in id_to_alarms.items():
            if rid not in alive:
                to_delete.extend(alarm_names)
                logger.info(
                    "Orphan alarms for %s %s: %s", rtype, rid, alarm_names,
                )

    if not to_delete:
        return []

    # CloudWatch delete_alarms는 최대 100개씩
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
