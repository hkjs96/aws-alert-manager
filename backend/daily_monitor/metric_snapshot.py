"""
Metric Snapshot — 주간 메트릭 장기 추이 수집

CloudWatch는 5분 해상도를 63일까지만 보관한다(이후 1시간 롤업).
주 1회 지난 7일의 일 단위 통계(p50/p95/p99/max/avg/min/표본수)를
MetricHistoryTable에 적재해 3개월+ 추이를 원 해상도 기반 통계로 보존한다.

- 수집 대상: Monitoring=on 리소스의 하드코딩 알람 정의 메트릭
  (disk처럼 인스턴스별 디멘션 조회가 필요한 dynamic_dimensions 정의는 V1 제외)
- 조회: GetMetricData (500쿼리/콜 배치, 계정×리전 단위 클라이언트)
- 저장: series_id = "{account_id}#{resource_id}#{metric_key}",
        period_start = "YYYY-MM-DD", TTL 91일
- 임계치 검증용으로 수집 시점의 적용 임계치(threshold_at_time)와
  비교 방향(comparison)을 함께 기록한다 — 재보정 도입 후 "바꿔서 좋아졌나"를
  이 테이블만으로 사후 검증하기 위함.

이 잡은 대상 계정 세션으로 CloudWatch만 읽고, DDB(메인 계정)는 기본 세션으로
쓴다 — 세션 전환(setup_default_session) 없이 동작한다.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from common.alarm_registry import _GLOBAL_SERVICE_REGION, _get_alarm_defs
from common.dimension_builder import _build_dimensions
from common.resource_discovery import _get_session_for_account, discover_resources
from common.threshold_resolver import resolve_threshold

logger = logging.getLogger(__name__)

# 일 단위 버킷으로 수집할 통계. GetMetricData 쿼리 1개 = (메트릭, 통계) 1쌍.
_STATS: tuple[tuple[str, str], ...] = (
    ("avg", "Average"),
    ("max", "Maximum"),
    ("min", "Minimum"),
    ("sample_count", "SampleCount"),
    ("p50", "p50"),
    ("p95", "p95"),
    ("p99", "p99"),
)

_PERIOD_SECONDS = 86400          # 일 단위 버킷
_RETENTION_DAYS = 91             # 13주 = 3개월 추이
_MAX_QUERIES_PER_CALL = 500      # GetMetricData 한도


def _ddb_num(value) -> Decimal:
    """DynamoDB는 float를 거부한다 — Decimal로 변환 (문자열 경유로 정밀도 유지)."""
    return Decimal(str(value))


def _build_queries_for_resource(resource: dict) -> list[dict]:
    """리소스의 하드코딩 알람 정의를 (쿼리 메타, MetricStat) 목록으로 변환.

    반환 항목: {"series_id", "metric_key", "comparison", "threshold",
               "namespace", "metric_name", "dimensions"}
    """
    resource_id = resource.get("resource_id") or resource.get("id", "")
    resource_type = resource.get("type", "")
    account_id = resource.get("account_id", "")
    tags = resource.get("tags") or {}

    entries = []
    for alarm_def in _get_alarm_defs(resource_type, tags):
        if alarm_def.get("dynamic_dimensions"):
            continue  # disk 등 인스턴스별 디멘션 조회 필요 — V1 제외
        metric_key = alarm_def.get("metric_key") or alarm_def["metric"]
        try:
            dimensions = _build_dimensions(alarm_def, resource_id, resource_type, tags)
            _thr, cw_threshold = resolve_threshold(alarm_def, tags)
        except (ClientError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Skipping snapshot query for %s/%s %s: %s",
                resource_type, resource_id, metric_key, e,
            )
            continue
        entries.append({
            "series_id": f"{account_id}#{resource_id}#{metric_key}",
            "metric_key": metric_key,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "account_id": account_id,
            "comparison": alarm_def.get("comparison", ""),
            "threshold": cw_threshold,
            "namespace": alarm_def["namespace"],
            "metric_name": alarm_def["metric_name"],
            "dimensions": dimensions,
        })
    return entries


def _query_region(resource: dict) -> str:
    """메트릭이 발행되는 리전 (글로벌 서비스는 us-east-1)."""
    return _GLOBAL_SERVICE_REGION.get(
        resource.get("type", ""), resource.get("region", "") or "us-east-1"
    )


def _fetch_metric_data(cw, entries: list[dict], start, end) -> dict[str, dict[str, dict]]:
    """GetMetricData 배치 실행.

    Returns:
        {series_id: {date_iso: {stat_key: value, ...}}}
    """
    # 쿼리 조립: entry × stat → MetricDataQuery. Id는 ^[a-z][a-zA-Z0-9_]*$ 제약.
    queries = []
    qid_map: dict[str, tuple[str, str]] = {}  # qid -> (series_id, stat_key)
    for i, entry in enumerate(entries):
        for j, (stat_key, stat) in enumerate(_STATS):
            qid = f"q{i}s{j}"
            qid_map[qid] = (entry["series_id"], stat_key)
            queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace": entry["namespace"],
                        "MetricName": entry["metric_name"],
                        "Dimensions": entry["dimensions"],
                    },
                    "Period": _PERIOD_SECONDS,
                    "Stat": stat,
                },
                "ReturnData": True,
            })

    rows: dict[str, dict[str, dict]] = {}
    for i in range(0, len(queries), _MAX_QUERIES_PER_CALL):
        chunk = queries[i:i + _MAX_QUERIES_PER_CALL]
        kwargs = {
            "MetricDataQueries": chunk,
            "StartTime": start,
            "EndTime": end,
            "ScanBy": "TimestampAscending",
        }
        while True:
            try:
                resp = cw.get_metric_data(**kwargs)
            except ClientError as e:
                logger.error("get_metric_data failed (chunk %d): %s", i, e)
                break
            for result in resp.get("MetricDataResults", []):
                mapping = qid_map.get(result.get("Id", ""))
                if not mapping:
                    continue
                series_id, stat_key = mapping
                for ts, val in zip(result.get("Timestamps", []), result.get("Values", [])):
                    date_iso = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
                    rows.setdefault(series_id, {}).setdefault(date_iso, {})[stat_key] = val
            token = resp.get("NextToken")
            if not token:
                break
            kwargs["NextToken"] = token
    return rows


def collect_weekly_snapshots(accounts: list[dict], *, days: int = 7) -> dict:
    """주간 스냅샷 수집 본체. 결과 통계 dict 반환."""
    table_name = os.environ.get("METRIC_HISTORY_TABLE")
    if not table_name:
        return {"skipped": "no_metric_history_table"}

    try:
        discovered = discover_resources(accounts)
    except ClientError as e:
        logger.error("discover_resources failed during metric snapshot: %s", e)
        return {"error": "discover_failed"}

    monitored = [r for r in discovered if r.get("monitoring")]

    # 계정×리전별로 쿼리를 묶는다 (GetMetricData 클라이언트 단위)
    account_by_id = {a.get("account_id", ""): a for a in accounts}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for resource in monitored:
        entries = _build_queries_for_resource(resource)
        if not entries:
            continue
        key = (resource.get("account_id", ""), _query_region(resource))
        grouped.setdefault(key, []).extend(entries)

    now = datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    collected_at = now.isoformat(timespec="seconds")
    ttl = int((now + timedelta(days=_RETENTION_DAYS)).timestamp())

    # series_id → 메타 (임계치 등) — 쓰기 시 참조
    meta_by_series = {
        e["series_id"]: e for entries in grouped.values() for e in entries
    }

    all_rows: dict[str, dict[str, dict]] = {}
    api_calls = 0
    for (account_id, region), entries in grouped.items():
        account = account_by_id.get(account_id)
        if account is None:
            logger.warning("No account metadata for %s — skipping %d queries", account_id, len(entries))
            continue
        session = _get_session_for_account(account, region)
        if session is None:
            continue
        cw = session.client("cloudwatch", region_name=region)
        rows = _fetch_metric_data(cw, entries, start, end)
        api_calls += (len(entries) * len(_STATS) + _MAX_QUERIES_PER_CALL - 1) // _MAX_QUERIES_PER_CALL
        for series_id, by_date in rows.items():
            all_rows.setdefault(series_id, {}).update(by_date)

    # DDB 적재 (메인 계정 기본 세션)
    table = boto3.resource("dynamodb").Table(table_name)
    written = 0
    try:
        with table.batch_writer(overwrite_by_pkeys=["series_id", "period_start"]) as batch:
            for series_id, by_date in all_rows.items():
                meta = meta_by_series.get(series_id, {})
                for date_iso, stats in by_date.items():
                    item = {
                        "series_id": series_id,
                        "period_start": date_iso,
                        "resource_id": meta.get("resource_id", ""),
                        "resource_type": meta.get("resource_type", ""),
                        "account_id": meta.get("account_id", ""),
                        "metric_key": meta.get("metric_key", ""),
                        "comparison": meta.get("comparison", ""),
                        "threshold_at_time": _ddb_num(meta.get("threshold", 0)),
                        "period_seconds": _PERIOD_SECONDS,
                        "collected_at": collected_at,
                        "ttl": ttl,
                    }
                    for stat_key, value in stats.items():
                        item[stat_key] = _ddb_num(value)
                    batch.put_item(Item=item)
                    written += 1
    except ClientError as e:
        logger.error("Metric snapshot batch write failed: %s", e)
        return {
            "resources": len(monitored), "series": len(all_rows),
            "rows_written": written, "error": "write_failed",
        }

    logger.info(
        "Metric snapshot: %d resources, %d series, %d rows, ~%d GetMetricData calls",
        len(monitored), len(all_rows), written, api_calls,
    )
    return {
        "resources": len(monitored),
        "series": len(all_rows),
        "rows_written": written,
        "get_metric_data_calls": api_calls,
    }
