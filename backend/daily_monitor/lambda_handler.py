"""
Daily_Monitor Lambda Handler (Worker)

Orchestrator로부터 계정 정보를 event로 받아 해당 계정의 리소스를 처리한다.

event 형식 (Orchestrator → Worker):
  {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/AlarmManagerRole"}
  role_arn가 빈 문자열이면 AssumeRole 없이 현재 Lambda 계정으로 실행 (단일 계정 모드).

직접 EventBridge로 invoke 시(event 미포함)에도 단일 계정 모드로 동작하여 기존 호환 유지.
"""

import functools
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

# Lambda 환경에서 root logger 레벨 설정 (모든 모듈에 적용)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from common.alarm_builder import resolve_alarm_severity
from common.alarm_index import AlarmIndex
from common.alarm_manager import sync_alarms_for_resource
from common.collectors.base import MetricBatch, set_active_metric_batch
from common.resource_discovery import (
    discover_resources,
    cleanup_stale_inventory,
    query_inventory_by_accounts,
)
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
from common.collectors import sqs as sqs_collector
from common.collectors import ecs as ecs_collector
from common.collectors import msk as msk_collector
from common.collectors import dynamodb as dynamodb_collector
from common.collectors import cloudfront as cloudfront_collector
from common.collectors import waf as waf_collector
from common.collectors import route53 as route53_collector
from common.collectors import dx as dx_collector
from common.collectors import efs as efs_collector
from common.collectors import s3 as s3_collector
from common.collectors import sagemaker as sagemaker_collector
from common.collectors import sns as sns_collector
from common.sns_notifier import send_alert, send_error_alert
from common.tag_resolver import get_resource_tags_or_none, get_threshold, has_monitoring_tag

# collector 모듈 목록 (런타임에 .get_metrics 참조하여 패치 가능하도록)
_COLLECTOR_MODULES = [
    ec2_collector, rds_collector, elb_collector, docdb_collector,
    elasticache_collector, natgw_collector,
    lambda_collector, vpn_collector, apigw_collector, acm_collector,
    backup_collector, mq_collector, clb_collector, opensearch_collector,
    sqs_collector, ecs_collector, msk_collector, dynamodb_collector,
    cloudfront_collector, waf_collector, route53_collector, dx_collector,
    efs_collector, s3_collector, sagemaker_collector, sns_collector,
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
    "SQS": sqs_collector,
    "ECS": ecs_collector,
    "MSK": msk_collector,
    "DynamoDB": dynamodb_collector,
    "CloudFront": cloudfront_collector,
    "WAF": waf_collector,
    "Route53": route53_collector,
    "DX": dx_collector,
    "EFS": efs_collector,
    "S3": s3_collector,
    "SageMaker": sagemaker_collector,
    "SNS": sns_collector,
}


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (거버넌스 §1)
# ──────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


@functools.lru_cache(maxsize=None)
def _get_ddb_resource():
    return boto3.resource("dynamodb")


# ──────────────────────────────────────────────
# 멀티 어카운트 세션 전환 (RISK-01, RISK-07 대응)
# ──────────────────────────────────────────────


def _switch_account_session(role_arn: str, account_id: str) -> None:
    """STS AssumeRole로 대상 계정 세션 전환 후 모든 lru_cache 클라이언트 무효화.

    boto3.setup_default_session()으로 프로세스 전체 기본 자격증명을 교체하므로
    이후 생성되는 모든 boto3 클라이언트가 대상 계정 credentials를 사용한다.
    Lambda는 컨테이너당 단일 invocation이므로 setup_default_session은 안전하다.
    Warm start 재사용 시 캐시된 이전 계정 클라이언트를 무효화하기 위해 cache_clear 필수.
    """
    sts = boto3.client("sts")
    try:
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"DailyMonitor-{account_id}",
        )
    except ClientError as e:
        logger.error("AssumeRole failed for %s (account=%s): %s", role_arn, account_id, e)
        raise

    creds = resp["Credentials"]
    boto3.setup_default_session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    _clear_all_client_caches()
    logger.info("Switched to account %s via AssumeRole", account_id)


def _clear_all_client_caches() -> None:
    """모든 모듈의 lru_cache boto3 클라이언트를 무효화하여 새 세션으로 재생성되도록 한다."""
    import common._clients as _cl
    import common.tag_resolver as tag_resolver
    from common.collectors import base as base_col

    # 핸들러 + 공통 모듈 클라이언트
    _get_cw_client.cache_clear()
    _get_ddb_resource.cache_clear()
    _cl._get_cw_client.cache_clear()
    _cl._get_cw_client_for_region.cache_clear()
    base_col._get_cw_client.cache_clear()
    for attr in dir(tag_resolver):
        fn = getattr(tag_resolver, attr, None)
        if attr.startswith("_get") and "client" in attr and callable(fn) and hasattr(fn, "cache_clear"):
            fn.cache_clear()

    # 각 collector 모듈의 _get_*_client 함수 일괄 무효화
    for mod in _COLLECTOR_MODULES:
        for attr in dir(mod):
            if attr.startswith("_get") and "client" in attr:
                fn = getattr(mod, attr, None)
                if callable(fn) and hasattr(fn, "cache_clear"):
                    fn.cache_clear()


def lambda_handler(event, context):
    # 수동 동기화 요청(Event) 분기 — 알람/리소스 둘 다 동일한 job 흐름
    if isinstance(event, dict) and event.get("sync_target") == "alarms":
        return _handle_alarms_sync_job(event, context)
    if isinstance(event, dict) and event.get("sync_target") == "resources":
        return _handle_resources_sync_job(event, context)
    # 주간 메트릭 스냅샷 (metric-snapshot-schedule → Orchestrator → mode 전달)
    if isinstance(event, dict) and event.get("mode") == "metric_snapshot":
        return _handle_metric_snapshot(event, context)
    """
    Lambda 핸들러 진입점 (Worker).

    event.role_arn이 있으면 해당 계정으로 세션 전환 후 처리.
    없으면 현재 Lambda 실행 계정(단일 계정 모드)으로 동작.

    0단계: 고아 알람 정리 (terminated 인스턴스 알람 삭제)
    1단계: 알람 동기화 (누락/불일치 점검)
    2단계: 메트릭 조회 → 임계치 비교 → 알림 발송

    Returns:
        {"status": "ok", "processed": N, "alerts": M, "alarms_synced": {...}}
    """
    # 멀티 어카운트: Orchestrator가 주입한 계정 정보로 세션 전환
    role_arn = event.get("role_arn", "") if isinstance(event, dict) else ""
    account_id = event.get("account_id", "self") if isinstance(event, dict) else "self"
    run_started_at = _utc_now_iso()
    run_started_ts = time.time()
    run_id = _build_monitor_run_id(account_id, context)
    run_table = _monitor_run_history_table()
    _put_monitor_run_start(run_table, run_id, run_started_at, account_id, event, context)
    _mark_stale_runs(run_table)

    # 0단계: ResourceInventoryTable 동기화 (세션 전환 전 — 메인 계정 DDB 접근 필요)
    # discover_resources()가 자체적으로 AssumeRole 하므로 세션 전환 불필요.
    prefetched_alarms: list[dict] = []
    try:
        inventory_stats = _sync_inventory(account_id, role_arn)
        prefetched_alarms = inventory_stats.pop("_alarms", [])
        logger.info("Inventory sync: %s", inventory_stats)
    except (ClientError, RuntimeError, KeyError) as e:
        logger.error("Inventory sync failed: %s", e)
        inventory_stats = {"error": str(e)}

    # 런 스코프 알람 인덱스: 인벤토리 동기화가 이미 조회한 전체 알람을 재사용해
    # 리소스별 describe_alarms 프리픽스 스캔(리소스 수 × 타입 알람 수)을 제거.
    # 페치 실패(빈 목록) 시에는 기존 라이브 조회로 폴백한다.
    alarm_index = AlarmIndex(prefetched_alarms) if prefetched_alarms else None

    if role_arn:
        try:
            _switch_account_session(role_arn, account_id)
        except ClientError:
            result = {"status": "error", "account_id": account_id, "reason": "assume_role_failed"}
            _finish_monitor_run(
                run_table, run_id, run_started_at, run_started_ts,
                "error", result, "assume_role_failed",
            )
            return result

    # 1단계: 고아 알람 정리
    try:
        orphaned = _cleanup_orphan_alarms()
        if orphaned:
            logger.info("Cleaned up orphan alarms: %s", orphaned)
    except ClientError as e:
        logger.error("Failed to cleanup orphan alarms: %s", e)
    total_processed = 0
    total_alerts = 0
    alarms_synced = {"created": 0, "updated": 0, "ok": 0}

    # 컬렉터별 리소스 수집 (메트릭 배치를 위해 목록을 먼저 확정)
    collected: list[tuple[object, list]] = []
    for collector_mod in _COLLECTOR_MODULES:
        try:
            resources = collector_mod.collect_monitored_resources()
        except ClientError as e:
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
        collected.append((collector_mod, resources))

    # 메트릭 배치: record(쿼리 수집, API 콜 없음) → execute(GetMetricData 일괄).
    # 리소스×메트릭당 1콜이던 get_metric_statistics를 500쿼리/콜로 줄인다.
    # record에서 누락된 쿼리는 serve 단계에서 라이브 폴백되므로 정확성은 동일.
    metric_batch = MetricBatch()
    set_active_metric_batch(metric_batch)
    metric_batch.record()
    for collector_mod, resources in collected:
        for resource in resources:
            try:
                _collect_resource_metrics(
                    resource["id"], resource["type"],
                    resource.get("tags", {}), collector_mod,
                )
            except (ClientError, RuntimeError, ValueError) as e:
                logger.warning(
                    "Metric recording failed for %s (%s): %s",
                    resource["id"], resource["type"], e,
                )
    metric_batch.execute()
    metric_batch.serve()

    try:
        for collector_mod, resources in collected:
            for resource in resources:
                resource_id = resource["id"]
                resource_type = resource["type"]
                resource_tags = resource.get("tags", {})

                # 1단계: 알람 동기화 (기존 알람 조회는 런 스코프 인덱스 사용)
                try:
                    sync_result = sync_alarms_for_resource(
                        resource_id, resource_type, resource_tags,
                        alarm_index=alarm_index,
                        resource_region=resource.get("region", ""),
                    )
                    alarms_synced["created"] += len(sync_result.get("created", []))
                    alarms_synced["updated"] += len(sync_result.get("updated", []))
                    alarms_synced["ok"] += len(sync_result.get("ok", []))
                except ClientError as e:
                    logger.error(
                        "Failed to sync alarms for %s (%s): %s",
                        resource_id, resource_type, e,
                    )

                # 2단계: 메트릭 조회 + 임계치 비교 (배치 캐시에서 응답)
                try:
                    alerts = _process_resource(
                        resource_id, resource_type, resource_tags, collector_mod
                    )
                    total_processed += 1
                    total_alerts += alerts
                except (ClientError, RuntimeError, ValueError) as e:
                    logger.error(
                        "Unexpected error processing resource %s (%s): %s",
                        resource_id, resource_type, e,
                    )
                    send_error_alert(
                        context=f"process_resource {resource_id} ({resource_type})",
                        error=e,
                    )
    finally:
        # 배치는 이 런 전용 — 다른 경로(sqs_worker 등)가 재사용하지 않도록 해제
        set_active_metric_batch(None)

    logger.info(
        "Daily monitor complete: account=%s, processed=%d, alerts=%d, alarms_synced=%s, inventory=%s",
        account_id, total_processed, total_alerts, alarms_synced, inventory_stats,
    )
    result = {
        "status": "ok",
        "account_id": account_id,
        "processed": total_processed,
        "alerts": total_alerts,
        "alarms_synced": alarms_synced,
        "inventory_synced": inventory_stats,
    }
    run_status = "partial" if inventory_stats.get("error") else "success"
    _finish_monitor_run(
        run_table, run_id, run_started_at, run_started_ts, run_status, result,
        inventory_stats.get("error"),
    )
    return result


def _handle_metric_snapshot(event: dict, context) -> dict:
    """주간 메트릭 스냅샷 잡 (mode=metric_snapshot).

    대상 계정 세션으로 CloudWatch만 읽고 메인 계정 DDB에 적재하므로
    세션 전환(_switch_account_session) 없이 동작한다.
    """
    from common.metric_snapshot import collect_weekly_snapshots

    account_id = event.get("account_id", "self")
    role_arn = event.get("role_arn", "")
    accounts = _resolve_accounts_for_inventory(account_id, role_arn)
    if not accounts:
        logger.warning("Metric snapshot: no account metadata for %s", account_id)
        return {"status": "ok", "skipped": "no_account_metadata"}

    stats = collect_weekly_snapshots(accounts)
    logger.info("Metric snapshot done for %s: %s", account_id, stats)
    return {"status": "ok", "account_id": account_id, **stats}


# ──────────────────────────────────────────────
# ResourceInventoryTable 동기화
# ──────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_monitor_run_id(account_id: str, context) -> str:
    request_id = getattr(context, "aws_request_id", "") if context else ""
    suffix = request_id or str(int(time.time() * 1000))
    return f"daily-monitor#{account_id}#{suffix}"


def _monitor_run_history_table():
    table_name = os.environ.get("MONITOR_RUN_HISTORY_TABLE")
    if not table_name:
        return None
    return _get_ddb_resource().Table(table_name)


# 워커 타임아웃(900s)보다 넉넉한 값. 이보다 오래 running이면 finish 레코드는 영영 오지 않는다.
_STALE_RUN_AFTER_SECONDS = 20 * 60
_STALE_RUN_LOOKBACK_DAYS = 7


def _mark_stale_runs(table, now_ts: float | None = None) -> int:
    """finish 기록 없이 running으로 남은 과거 run을 timeout으로 정정한다.

    Lambda가 타임아웃/강제 종료되면 _finish_monitor_run이 실행되지 않아 레코드가
    영구히 running으로 남는다(2026-08-31 dev 계정 실사례). 다음 run 시작 시 정정한다.
    조회 범위는 최근 N일로 제한해 히스토리 전체를 읽지 않는다.
    """
    if table is None:
        return 0
    now_ts = now_ts if now_ts is not None else time.time()
    cutoff = datetime.fromtimestamp(now_ts - _STALE_RUN_AFTER_SECONDS, tz=timezone.utc)
    lookback = datetime.fromtimestamp(now_ts - _STALE_RUN_LOOKBACK_DAYS * 86400, tz=timezone.utc)
    to_iso = lambda d: d.isoformat(timespec="seconds").replace("+00:00", "Z")  # noqa: E731

    stale: list[dict] = []
    kwargs = {
        "KeyConditionExpression": (
            Key("scope").eq("daily_monitor")
            & Key("started_at").between(to_iso(lookback), to_iso(cutoff))
        ),
        "FilterExpression": Attr("status").eq("running"),
    }
    try:
        while True:
            resp = table.query(**kwargs)
            stale.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except ClientError as e:
        logger.error("Stale run query failed: %s", e)
        return 0

    fixed = 0
    for item in stale:
        try:
            table.update_item(
                Key={"scope": "daily_monitor", "started_at": item["started_at"]},
                UpdateExpression="SET #s = :status, error_message = :err, stale_marked_at = :now",
                # 그 사이 finish가 기록됐다면 건드리지 않는다.
                ConditionExpression="#s = :running",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": "timeout",
                    ":running": "running",
                    ":err": "no finish record within lambda timeout (marked stale by a later run)",
                    ":now": to_iso(datetime.fromtimestamp(now_ts, tz=timezone.utc)),
                },
            )
            fixed += 1
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                logger.error("Stale run update failed for %s: %s", item.get("run_id"), e)
    if fixed:
        logger.warning("Marked %d stale running run(s) as timeout", fixed)
    return fixed


def _put_monitor_run_start(
    table, run_id: str, started_at: str, account_id: str, event, context,
) -> None:
    if table is None:
        return
    item = {
        "scope": "daily_monitor",
        "started_at": started_at,
        "run_id": run_id,
        "account_id": account_id,
        "status": "running",
        "trigger": _monitor_run_trigger(event),
        "lambda_request_id": getattr(context, "aws_request_id", "") if context else "",
        "ttl": int(time.time()) + 90 * 24 * 60 * 60,
    }
    try:
        table.put_item(Item=item)
    except ClientError as e:
        logger.error("Monitor run start write failed: %s", e)


def _finish_monitor_run(
    table, run_id: str, started_at: str, started_ts: float,
    status: str, result: dict, error_message: str | None = None,
) -> None:
    if table is None:
        return
    values = {
        ":status": status,
        ":finished_at": _utc_now_iso(),
        ":duration_ms": int((time.time() - started_ts) * 1000),
        ":summary": _monitor_run_summary(result),
    }
    update_expr = (
        "SET #s = :status, finished_at = :finished_at, "
        "duration_ms = :duration_ms, summary = :summary"
    )
    if error_message:
        update_expr += ", error_message = :error_message"
        values[":error_message"] = str(error_message)
    try:
        table.update_item(
            Key={"scope": "daily_monitor", "started_at": started_at},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=values,
        )
    except ClientError as e:
        logger.error("Monitor run finish write failed: %s", e)


def _monitor_run_trigger(event) -> str:
    if not isinstance(event, dict):
        return "unknown"
    if event.get("source") == "aws.scheduler":
        return "schedule"
    if event.get("account_id") or event.get("role_arn"):
        return "orchestrator"
    return "manual"


def _monitor_run_summary(result: dict) -> dict:
    alarms = result.get("alarms_synced") or {}
    inventory = result.get("inventory_synced") or {}
    return {
        "processed": result.get("processed", 0),
        "alerts": result.get("alerts", 0),
        "alarms_created": alarms.get("created", 0),
        "alarms_updated": alarms.get("updated", 0),
        "alarms_ok": alarms.get("ok", 0),
        "inventory_discovered": inventory.get("discovered", 0),
        "inventory_synced": inventory.get("synced", 0),
    }


def _fetch_alarms_for_accounts(accounts: list[dict]) -> list[dict]:
    from common.resource_discovery import _get_session_for_account
    all_alarms = []
    for account in accounts:
        regions = account.get("regions") or ["ap-northeast-2"]
        account_id = account.get("account_id")
        for region in regions:
            session = _get_session_for_account(account, region)
            if not session:
                continue
            try:
                cw = session.client("cloudwatch")
                paginator = cw.get_paginator("describe_alarms")
                # 프리픽스 없이 전체 조회: 이 결과가 런 스코프 AlarmIndex의 원천이라
                # 레거시 포맷({resource_id}-...) 알람까지 포함해야 한다. 인벤토리
                # 스냅샷 기록은 _write_alarm_snapshots에서 관리 알람만 필터링한다.
                for page in paginator.paginate(AlarmTypes=["MetricAlarm"]):
                    for alarm in page.get("MetricAlarms", []):
                        alarm["_region"] = region
                        alarm["_account_id"] = account_id
                        all_alarms.append(alarm)
            except ClientError as e:
                logger.error("Failed to describe alarms in %s/%s: %s", account_id, region, e)
    return all_alarms


def _extract_resource_from_alarm_name(name: str) -> tuple[str, str] | None:
    m = _NEW_FORMAT_RE.match(name)
    if m:
        return m.group(1), m.group(2)
    legacy = re.match(r"^(i-[0-9a-f]+)-", name)
    if legacy:
        return "EC2", legacy.group(1)
    return None


def _is_alarm_critical(alarm: dict) -> bool:
    return resolve_alarm_severity(alarm) in ("SEV-1", "SEV-2")


def _determine_alarm_state(alarms: list[dict]) -> str:
    if not alarms:
        return "OK"
    states = {a.get("StateValue") for a in alarms}
    if "ALARM" in states:
        return "ALARM"
    if "INSUFFICIENT_DATA" in states:
        return "INSUFFICIENT_DATA"
    return "OK"


# 리소스 항목에 얹히는 알람 집계 필드. 디스커버리 결과에는 없으므로 upsert 시 보존한다.
_ALARM_ROLLUP_FIELDS = (
    "alarm_count",
    "critical_count",
    "warning_count",
    "alarm_names",
    "alarm_state",
    "last_alarm_synced_at",
)


def _batch_put_items(inv_table, items: list[dict]) -> int:
    """인벤토리 항목을 batch_writer로 일괄 저장하고 저장한 개수를 반환한다.

    항목마다 put_item을 호출하면 리소스·알람 수만큼 왕복이 생긴다. batch_writer는
    25개씩 묶고 UnprocessedItems를 자동 재시도한다. 한 배치 안에 같은 키가 두 번
    들어가면 BatchWriteItem이 거부하므로 overwrite_by_pkeys로 정리한다.
    """
    if not items:
        return 0
    try:
        with inv_table.batch_writer(
            overwrite_by_pkeys=["resource_id", "account_id"]
        ) as batch:
            for item in items:
                batch.put_item(Item=item)
    except ClientError as e:
        logger.error("Inventory batch write failed (%d items): %s", len(items), e)
        return 0
    return len(items)


def _batch_delete_keys(inv_table, keys: list[dict]) -> int:
    """인벤토리 항목을 batch_writer로 일괄 삭제하고 삭제한 개수를 반환한다."""
    if not keys:
        return 0
    try:
        with inv_table.batch_writer(
            overwrite_by_pkeys=["resource_id", "account_id"]
        ) as batch:
            for key in keys:
                batch.delete_item(Key=key)
    except ClientError as e:
        logger.error("Inventory batch delete failed (%d keys): %s", len(keys), e)
        return 0
    return len(keys)


def _stale_alarm_keys(
    db_items: list[dict],
    fresh_keys: set[tuple[str, str]],
    is_target,
) -> list[dict]:
    """이번 실행에서 갱신되지 않은 알람 스냅샷의 키 목록."""
    keys = []
    for item in db_items:
        if item.get("entity_type") != "alarm":
            continue
        res_id = item.get("resource_id", "")
        acc_id = item.get("account_id", "")
        if not is_target(item):
            continue
        if (res_id, acc_id) in fresh_keys:
            continue
        keys.append({"resource_id": res_id, "account_id": acc_id})
    return keys


def _group_alarms_by_resource(alarms: list[dict]) -> dict[str, list[dict]]:
    """알람을 리소스 식별자별로 묶는다."""
    grouped: dict[str, list[dict]] = {}
    for alarm in alarms:
        extracted = _extract_resource_from_alarm_name(alarm["AlarmName"])
        if extracted:
            _rtype, rid = extracted
            grouped.setdefault(rid, []).append(alarm)
    return grouped


def _build_resource_items(
    discovered: list[dict],
    resource_alarms_map: dict[str, list[dict]],
) -> list[dict]:
    """디스커버리 결과를 인벤토리 항목으로 변환하고 알람 집계 필드를 채운다."""
    items = []
    synced_at = datetime.now(timezone.utc).isoformat()
    for resource in discovered:
        item = _sanitize_inventory_item(resource)
        if not item.get("resource_id") or not item.get("account_id"):
            continue

        item["entity_type"] = "resource"

        res_alarms = resource_alarms_map.get(item["resource_id"], [])
        firing = [a for a in res_alarms if a.get("StateValue") == "ALARM"]
        item["alarm_count"] = len(res_alarms)
        item["critical_count"] = sum(1 for a in firing if _is_alarm_critical(a))
        item["warning_count"] = len(firing) - item["critical_count"]
        item["alarm_names"] = [a["AlarmName"] for a in res_alarms]
        item["alarm_state"] = _determine_alarm_state(res_alarms)
        item["last_alarm_synced_at"] = synced_at

        items.append(item)
    return items


def _sync_inventory(account_id_hint: str, role_arn: str) -> dict:
    """대상 계정의 리소스를 discover하여 ResourceInventoryTable에 upsert.

    반드시 _switch_account_session() 호출 전에 실행해야 한다.
    이유: ResourceInventoryTable은 메인 계정에 있는데, 세션 전환 후에는
    대상 계정의 DDB를 보게 되어 write가 실패한다.

    discover_resources()는 account 객체의 role_arn을 보고 자체적으로 assume role
    하므로, 여기서는 default session(메인 계정)을 유지한 채 호출한다.
    """
    inv_table_name = os.environ.get("RESOURCE_INVENTORY_TABLE")
    if not inv_table_name:
        return {"discovered": 0, "synced": 0, "skipped": "no_inventory_table"}

    accounts = _resolve_accounts_for_inventory(account_id_hint, role_arn)
    if not accounts:
        return {"discovered": 0, "synced": 0, "skipped": "no_account_metadata"}

    try:
        discovered = discover_resources(accounts)
    except ClientError as e:
        logger.error("discover_resources failed during inventory sync: %s", e)
        return {"discovered": 0, "synced": 0, "error": "discover_failed"}

    try:
        alarms = _fetch_alarms_for_accounts(accounts)
    except ClientError as e:
        logger.error("Failed to fetch alarms during inventory sync: %s", e)
        alarms = []

    ddb = boto3.resource("dynamodb")
    inv_table = ddb.Table(inv_table_name)

    resource_items = _build_resource_items(discovered, _group_alarms_by_resource(alarms))
    synced = _batch_put_items(inv_table, resource_items)

    # 정리에 쓸 기존 인벤토리 항목은 account_id-index GSI로 한 번만 조회한다.
    # 리소스 정리와 알람 정리가 이 결과를 공유하므로 전체 테이블 Scan이 필요 없다.
    # 조회/정리 실패는 로깅만 하고 동기화는 계속 진행한다.
    db_items: list[dict] = []
    try:
        account_ids = [a["account_id"] for a in accounts]
        db_items = query_inventory_by_accounts(inv_table, account_ids)
        cleanup_stale_inventory(inv_table, db_items, discovered, log=logger)
    except ClientError as e:
        logger.error("Failed to query inventory for stale resource cleanup: %s", e)

    # Save alarm snapshot items — 알람 잡(_handle_alarms_sync_job)과 같은 경로를 쓴다.
    # 예전에는 여기에 같은 아이템 생성 코드가 복제돼 있어 한쪽만 고치는 사고가 났다.
    synced_alarms, fresh_alarm_keys = _write_alarm_snapshots(inv_table, alarms)

    # Cleanup stale alarms for synchronized accounts — 위에서 GSI로 읽은 항목을
    # 재사용한다. 이번 실행에서 새로 쓴 알람은 db_items에 없으므로 삭제 대상이 아니다.
    target_accounts = {acc["account_id"] for acc in accounts}
    stale_keys = _stale_alarm_keys(
        db_items,
        fresh_alarm_keys,
        lambda item: item.get("account_id", "") in target_accounts,
    )
    deleted_alarms = _batch_delete_keys(inv_table, stale_keys)
    logger.info(
        "Inventory sync: %d resources, %d alarm snapshots, %d stale alarms removed",
        synced, synced_alarms, deleted_alarms,
    )

    # "_alarms": 이번 런에서 이미 조회한 전체 알람 — lambda_handler가 꺼내
    # AlarmIndex를 만들어 리소스별 재조회를 없앤다. run history에 기록되기 전에
    # 호출부에서 pop 하므로 요약에는 남지 않는다.
    return {"discovered": len(discovered), "synced": synced, "_alarms": alarms}


def _resolve_accounts_for_inventory(account_id_hint: str, role_arn: str) -> list[dict]:
    """ACCOUNTS_TABLE에서 regions/customer_id 메타데이터를 채워 account 객체 구성.

    GSI account_id-index로 account_id 기준 조회.
    ACCOUNTS_TABLE이 없거나 항목이 없으면 기본 region으로 fallback.
    single-account 모드(account_id_hint="self")에서는 STS로 실제 ID를 확인.
    """
    accounts_table_name = os.environ.get("ACCOUNTS_TABLE")

    if not account_id_hint or account_id_hint == "self":
        try:
            real_id = boto3.client("sts").get_caller_identity()["Account"]
        except ClientError as e:
            logger.error("get_caller_identity failed during inventory sync: %s", e)
            return []
        target_account_id = real_id
        target_role_arn = ""
    else:
        target_account_id = account_id_hint
        target_role_arn = role_arn

    fallback = [{
        "account_id": target_account_id,
        "role_arn": target_role_arn,
        "regions": ["ap-northeast-2"],
        "customer_id": "",
    }]

    if not accounts_table_name:
        return fallback

    try:
        table = boto3.resource("dynamodb").Table(accounts_table_name)
        resp = table.query(
            IndexName="account_id-index",
            KeyConditionExpression=Key("account_id").eq(target_account_id),
        )
    except ClientError as e:
        logger.warning(
            "AccountsTable query failed for %s, using fallback: %s",
            target_account_id, e,
        )
        return fallback

    items = resp.get("Items", [])
    if not items:
        return fallback

    item = items[0]
    return [{
        "account_id": target_account_id,
        "role_arn": target_role_arn,
        "regions": list(item.get("regions") or ["ap-northeast-2"]),
        "customer_id": item.get("customer_id", "") or "",
    }]


# 인벤토리에 영속화할 collector 내부 디멘션 힌트 키.
# APIGW(_api_type: REST는 ApiName, HTTP/WS는 ApiId), ECS(_cluster_name),
# SageMaker(_variant_name), OpenSearch(_client_id), WAF(_waf_rule),
# ELB 계열(_lb_arn/_lb_type/_target_type — TG 알람 디멘션·정책 분기용).
_DIM_HINT_KEYS = (
    "_api_type", "_cluster_name", "_variant_name", "_client_id",
    "_waf_rule", "_lb_arn", "_lb_type", "_target_type",
)


def _sanitize_inventory_item(resource: dict) -> dict:
    """DDB 저장용으로 정규화. tags/arn 등 변동성 큰 필드는 제외.

    customer_id가 비어있으면 attribute 자체를 제외하여 GSI(customer_id-index)에
    들어가지 않도록 한다 (DDB는 빈 문자열 GSI key를 허용하지 않음).
    """
    item = {
        "resource_id": resource.get("resource_id", ""),
        "account_id": resource.get("account_id", "") or "",
        "name": resource.get("name", ""),
        "type": resource.get("type", ""),
        "region": resource.get("region", ""),
        "monitoring": bool(resource.get("monitoring", False)),
        "status": resource.get("status", "active"),
    }
    customer_id = resource.get("customer_id")
    if customer_id:
        item["customer_id"] = customer_id
    # ARN은 모니터링 토글(Resource Groups Tagging API)에서 사용하므로 영속화한다.
    arn = resource.get("arn")
    if arn:
        item["arn"] = arn
    # 디멘션 힌트: compound-dimension 타입(APIGW v2의 ApiId, ECS의 ClusterName 등)의
    # 상세 메트릭 조회/알람 생성에 필요한 collector 내부 태그만 화이트리스트 영속화.
    # tags 전체는 변동성이 커서 여전히 제외한다.
    tags = resource.get("tags") or {}
    hints = {k: tags[k] for k in _DIM_HINT_KEYS if tags.get(k)}
    if hints:
        item["dim_hints"] = hints
    return item


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
                continue
            if not _is_currently_monitored(rid, rtype):
                to_delete.extend(alarm_names)
                logger.info(
                    "Monitoring disabled for %s %s: deleting alarms %s",
                    rtype, rid, alarm_names,
                )

    if not to_delete:
        return []

    cw = _get_cw_client()
    for i in range(0, len(to_delete), 100):
        cw.delete_alarms(AlarmNames=to_delete[i:i + 100])

    logger.info("Deleted %d orphan alarms", len(to_delete))
    return to_delete


def _is_currently_monitored(resource_id: str, resource_type: str) -> bool:
    tags = get_resource_tags_or_none(resource_id, resource_type)
    if tags is None:
        logger.warning(
            "Skipping alarm cleanup for %s %s because tags could not be read",
            resource_type, resource_id,
        )
        return True
    return has_monitoring_tag(tags)


def _collect_resource_metrics(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    collector_mod,
) -> dict[str, float] | None:
    """컬렉터 get_metrics 호출 (타입별 호출 형태 단일화).

    메트릭 배치의 record 단계와 본 실행이 반드시 같은 경로를 타야
    기록된 쿼리와 실제 쿼리가 일치한다.
    """
    if resource_type == "TG":
        # ELB TG의 경우 lb_arn 태그 전달
        lb_arn = resource_tags.get("_lb_arn")
        return collector_mod.get_metrics(resource_id, resource_tags, lb_arn=lb_arn)
    if resource_type == "AuroraRDS":
        return collector_mod.get_aurora_metrics(resource_id, resource_tags)
    return collector_mod.get_metrics(resource_id, resource_tags)


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
    metrics = _collect_resource_metrics(
        resource_id, resource_type, resource_tags, collector_mod
    )

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
                          "TunnelState", "DaysToExpiry", "OSFreeStorageSpace",
                          "ActiveControllerCount",
                          "HealthCheckStatus", "ConnectionState", "BurstCreditBalance"):
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


def _job_status_table():
    table_name = os.environ.get("JOB_STATUS_TABLE")
    if not table_name:
        return None
    return _get_ddb_resource().Table(table_name)


def _update_job_status(job_id: str, status: str, extra: dict | None = None) -> None:
    job_table = _job_status_table()
    if not job_table or not job_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    expr = "SET #s = :status, updated_at = :updated_at"
    vals = {":status": status, ":updated_at": now}
    if extra:
        for k, v in extra.items():
            expr += f", {k} = :{k}"
            vals[f":{k}"] = v
    try:
        job_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=expr,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=vals
        )
    except ClientError as e:
        logger.error("Failed to update job status %s to %s: %s", job_id, status, e)


def _resolve_target_accounts(scope: dict) -> list[dict]:
    customer_id = scope.get("customer_id")
    account_id = scope.get("account_id")
    table_name = os.environ.get("ACCOUNTS_TABLE")
    if not table_name:
        return _fallback_single_account()

    try:
        table = _get_ddb_resource().Table(table_name)
        if customer_id and account_id:
            res = table.get_item(Key={"customer_id": customer_id, "account_id": account_id})
            return [res["Item"]] if res.get("Item") else []
        if customer_id:
            return table.query(KeyConditionExpression=Key("customer_id").eq(customer_id)).get("Items", [])
        if account_id:
            return table.query(IndexName="account_id-index", KeyConditionExpression=Key("account_id").eq(account_id)).get("Items", [])
        return _scan_all_accounts(table)
    except ClientError as e:
        logger.error("Failed to resolve target accounts: %s", e)
        raise


def _fallback_single_account() -> list[dict]:
    sts = boto3.client("sts")
    real_id = sts.get_caller_identity()["Account"]
    return [{
        "account_id": real_id,
        "role_arn": "",
        "regions": ["ap-northeast-2"],
        "customer_id": "",
    }]


def _scan_all_accounts(table) -> list[dict]:
    items = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def _write_alarm_snapshots(inv_table, alarms: list[dict]) -> tuple[int, set[tuple[str, str]]]:
    items = []
    fresh_keys = set()
    for alarm in alarms:
        # 인벤토리에는 이 엔진이 관리하는 포맷의 알람만 기록한다.
        # (페치는 AlarmIndex용으로 전체를 가져온다.) 단순 "[" 접두사 필터는
        # CFN이 만든 [RemediationDLQ] 같은 인프라 알람까지 리소스 없는 유령 행으로
        # 넣었으므로, 리소스를 역추출할 수 있는 관리 포맷만 통과시킨다.
        if _extract_resource_from_alarm_name(alarm.get("AlarmName", "")) is None:
            continue
        arn = alarm.get("AlarmArn", "")
        if not arn:
            continue
        db_key = f"alarm#{arn}"
        arn_parts = arn.split(":")
        acc = arn_parts[4] if len(arn_parts) > 4 and arn_parts[4] else alarm.get("_account_id", "unknown")

        items.append(_build_alarm_item(alarm, db_key, acc, arn_parts))
        fresh_keys.add((db_key, acc))

    return _batch_put_items(inv_table, items), fresh_keys


def _build_alarm_item(alarm: dict, db_key: str, account: str, arn_parts: list[str]) -> dict:
    alarm_name = alarm["AlarmName"]
    region = arn_parts[3] if len(arn_parts) > 3 and arn_parts[3] else alarm.get("_region", "unknown")
    
    res_id, res_type = "", ""
    extracted = _extract_resource_from_alarm_name(alarm_name)
    if extracted:
        res_type, res_id = extracted
    else:
        res_id = alarm_name

    tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
    severity = resolve_alarm_severity(alarm)
    ts = alarm.get("StateUpdatedTimestamp")
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")

    return {
        "resource_id": db_key,
        "account_id": account,
        "alarm_name": alarm_name,
        "arn": alarm.get("AlarmArn", ""),
        "entity_type": "alarm",
        "state": alarm.get("StateValue", ""),
        "metric": alarm.get("MetricName", ""),
        "namespace": alarm.get("Namespace", ""),
        "comparison": alarm.get("ComparisonOperator", ""),
        "threshold": str(alarm.get("Threshold", "0")),
        "severity": severity,
        "time": ts_str,
        "region": region,
        "type": res_type,
        "resource": res_id,
        "inventory_source": "alarms",
        "tags": tags,
        "status": "active",
        "period": alarm.get("Period"),
        "evaluation_periods": alarm.get("EvaluationPeriods"),
        "datapoints_to_alarm": alarm.get("DatapointsToAlarm"),
        "treat_missing_data": alarm.get("TreatMissingData"),
        "statistic": alarm.get("Statistic"),
    }


def _cleanup_stale_snapshots(inv_table, fresh_keys: set[tuple[str, str]], target_acc_regions: set[tuple[str, str]]) -> int:
    # 정리 대상은 동기화한 계정뿐이므로 account_id-index GSI 조회로 충분하다.
    # 전체 Scan은 테이블이 커질수록 비용/시간이 선형으로 늘어난다.
    account_ids = {acc for acc, _ in target_acc_regions}
    try:
        db_items = query_inventory_by_accounts(inv_table, account_ids)
    except ClientError as e:
        logger.error("Failed to query inventory for alarm cleanup: %s", e)
        return 0

    stale_keys = _stale_alarm_keys(
        db_items,
        fresh_keys,
        lambda item: (item.get("account_id", ""), item.get("region", "")) in target_acc_regions,
    )
    return _batch_delete_keys(inv_table, stale_keys)


def _handle_alarms_sync_job(event: dict, context) -> dict:
    job_id = event.get("sync_job_id", "")
    scope = event.get("scope", {})
    regions_override = scope.get("regions") or []
    
    _update_job_status(job_id, "in_progress")

    # 고아 알람 정리: 존재하지 않는 리소스의 CloudWatch 알람을 삭제한다.
    # 현재/기본 계정(단일 계정 모드) 대상이며, AssumeRole 대상 계정은 스케줄
    # daily flow가 처리한다. 실패해도 알람 동기화는 계속 진행한다.
    try:
        orphaned = _cleanup_orphan_alarms()
        if orphaned:
            logger.info("Alarm sync removed %d orphan alarms", len(orphaned))
    except ClientError as e:
        logger.error("Orphan alarm cleanup failed during alarm sync: %s", e)

    try:
        accounts = _resolve_target_accounts(scope)
    except ClientError as e:
        _update_job_status(job_id, "failed", {"error_message": f"DB_ERROR: {e}"})
        return {"status": "error", "message": str(e)}

    if not accounts:
        _update_job_status(job_id, "failed", {"error_message": "No matching accounts found"})
        return {"status": "ok", "message": "No matching accounts found"}

    for acc in accounts:
        acc["regions"] = regions_override if regions_override else list(acc.get("regions") or ["ap-northeast-2"])

    try:
        alarms = _fetch_alarms_for_accounts(accounts)
    except ClientError as e:
        _update_job_status(job_id, "failed", {"error_message": f"AWS_ERROR: {e}"})
        return {"status": "error", "message": str(e)}

    inv_table_name = os.environ.get("RESOURCE_INVENTORY_TABLE")
    synced, deleted = 0, 0
    if inv_table_name:
        inv_table = _get_ddb_resource().Table(inv_table_name)
        synced, fresh = _write_alarm_snapshots(inv_table, alarms)
        
        target_acc_regions = {(acc["account_id"], reg) for acc in accounts for reg in acc["regions"]}
        deleted = _cleanup_stale_snapshots(inv_table, fresh, target_acc_regions)

    results = [{
        "account_id": acc["account_id"],
        "regions": acc["regions"],
        "status": "success",
        "imported": synced,
        "deleted": deleted
    } for acc in accounts]

    _update_job_status(job_id, "completed", {
        "completed_count": len(accounts),
        "failed_count": 0,
        "results": results
    })

    return {"status": "ok", "imported": synced, "deleted": deleted}


def _write_resources_to_inventory(inv_table, discovered: list[dict]) -> int:
    """디스커버리 결과를 인벤토리에 upsert. 기존 알람 집계 필드는 보존한다."""
    items = []
    for resource in discovered:
        item = _sanitize_inventory_item(resource)
        if not item.get("resource_id") or not item.get("account_id"):
            continue
        item["entity_type"] = "resource"
        items.append(item)

    if not items:
        return 0

    # 알람 집계 필드를 보존하려면 기존 값을 알아야 한다. 리소스마다 get_item을 호출하면
    # 리소스 수만큼 왕복이 생기므로, 계정 단위 GSI 조회로 한 번에 읽는다.
    account_ids = {item["account_id"] for item in items}
    try:
        existing_items = query_inventory_by_accounts(inv_table, account_ids)
    except ClientError as e:
        logger.error("Failed to query existing inventory for rollup merge: %s", e)
        existing_items = []
    existing_by_key = {
        (i.get("resource_id"), i.get("account_id")): i for i in existing_items
    }

    for item in items:
        existing = existing_by_key.get((item["resource_id"], item["account_id"]))
        if not existing:
            continue
        for field in _ALARM_ROLLUP_FIELDS:
            if field in existing:
                item[field] = existing[field]

    return _batch_put_items(inv_table, items)


def _handle_resources_sync_job(event: dict, context) -> dict:
    """리소스 인벤토리 동기화 잡 (sync_target=resources). 알람 잡과 동일한 흐름.

    scope로 대상 계정을 해석 → discover_resources → 인벤토리 upsert + stale 정리 →
    job status를 discovered/synced/removed로 갱신한다.
    """
    job_id = event.get("sync_job_id", "")
    scope = event.get("scope", {})
    regions_override = scope.get("regions") or []

    _update_job_status(job_id, "in_progress")

    try:
        accounts = _resolve_target_accounts(scope)
    except ClientError as e:
        _update_job_status(job_id, "failed", {"error_message": f"DB_ERROR: {e}"})
        return {"status": "error", "message": str(e)}

    if not accounts:
        _update_job_status(job_id, "failed", {"error_message": "No matching accounts found"})
        return {"status": "ok", "message": "No matching accounts found"}

    for acc in accounts:
        acc["regions"] = regions_override if regions_override else list(acc.get("regions") or ["ap-northeast-2"])

    inv_table_name = os.environ.get("RESOURCE_INVENTORY_TABLE")
    discovered_count, synced, removed = 0, 0, 0
    if inv_table_name:
        try:
            discovered = discover_resources(accounts)
        except ClientError as e:
            _update_job_status(job_id, "failed", {"error_message": f"AWS_ERROR: {e}"})
            return {"status": "error", "message": str(e)}

        inv_table = _get_ddb_resource().Table(inv_table_name)
        discovered_count = len(discovered)
        synced = _write_resources_to_inventory(inv_table, discovered)
        try:
            account_ids = [a["account_id"] for a in accounts]
            db_items = query_inventory_by_accounts(inv_table, account_ids)
            removed = cleanup_stale_inventory(inv_table, db_items, discovered, log=logger)
        except ClientError as e:
            logger.error("Resource sync stale cleanup failed: %s", e)

    results = [{
        "account_id": acc["account_id"],
        "regions": acc["regions"],
        "status": "success",
        "discovered": discovered_count,
        "synced": synced,
        "removed": removed,
    } for acc in accounts]

    _update_job_status(job_id, "completed", {
        "completed_count": len(accounts),
        "failed_count": 0,
        "results": results,
    })

    return {"status": "ok", "discovered": discovered_count, "synced": synced, "removed": removed}
