"""
임계치 재보정 — Shadow 모드 (주 1회, 제안만 기록, 알람은 건드리지 않는다)

MetricHistoryTable(주간 스냅샷, 일 단위 p99/max)을 읽어 리소스×메트릭별 "트래픽 기반"
임계치 제안을 계산하고 ThresholdOverridesTable에 `status=shadow` 행으로 남긴다.
2주 이상 관측해 "제안대로 바꿨다면 알람 발화일이 얼마나 줄었을까"(breach_days_*)를
확인한 뒤 PoC(실제 적용)로 넘어간다 — docs/reports/IMPROVEMENT-ROADMAP.md P2.

산식과 가드 (전부 설명 가능해야 한다 — "28일 중 최고 일 p99 × 1.2"):
  1. 대상: `GreaterThanThreshold` 메트릭 중 정책 표(_POLICY)에 있는 것만.
     1순위 순수 트래픽(RequestCount …, 현재 전 리소스 고정값이 오탐 근원), 2순위 지연,
     3순위 CPU(포화 지표 — 절대 클램프 필수). 가용성 이진(StatusCheckFailed 등)·에러
     카운트(5XX)·SEV-1/2 원천은 제외.
  2. 데이터 충분성: 최근 28일 중 21일 이상 p99가 있어야 한다.
  3. 기준값 = 창 안 일 p99의 최댓값 × 헤드룸 1.2 → 절대 클램프(lo/hi) → 사이클당 변화율
     상한 ±25% → 현재값 대비 5% 미만이면 유지(hysteresis: sync가 0.001 차이도 재생성한다).
  4. 효과 추정: 창 안에서 일 max가 현재/제안 임계치를 넘은 날 수(근사 — 실제 알람은
     5분 데이터포인트 M-of-N).

Shadow 행은 `threshold_value` 속성을 갖지 않으므로 고객사 오버라이드 조회
(scope_id=customer_id:…)와 절대 섞이지 않는다. 킬 스위치 없음 — 읽기+제안 기록뿐이다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common.alarm_registry import get_severity
from common.metric_snapshot import _build_queries_for_resource
from common.resource_discovery import discover_resources

logger = logging.getLogger(__name__)

WINDOW_DAYS = 28
MIN_DAYS = 21
HEADROOM = 1.2
RATE_CAP = 0.25
HYSTERESIS = 0.05
EXCLUDED_SEVERITIES = ("SEV-1", "SEV-2")
PROPOSAL_TTL_DAYS = 35

# metric_key → (kind, clamp_lo, clamp_hi). None = 클램프 없음.
_POLICY: dict[str, tuple[str, float | None, float | None]] = {
    # 1순위 — 순수 트래픽 (리소스별 편차가 커서 고정 임계치의 오탐 근원)
    "RequestCount": ("traffic", None, None),
    "RequestCountPerTarget": ("traffic", None, None),
    "ProcessedBytes": ("traffic", None, None),
    "NewFlowCount": ("traffic", None, None),
    # 2순위 — 지연 (사용자 체감; 정상 대비 회귀 감지)
    "TargetResponseTime": ("latency", None, None),
    "ApiLatency": ("latency", None, None),
    # 3순위 — CPU (포화 지표: 절대 경계 밖으로 나가면 안 된다)
    "CPUUtilization": ("saturation", 70.0, 95.0),
}


@dataclass
class Proposal:
    status: str                 # "proposed" | "hold" | "excluded"
    reason: str                 # 주 사유 (hold/excluded) 또는 "p99x1.2"
    current: float
    proposed: float | None = None
    reasons: list[str] = field(default_factory=list)
    days_available: int = 0
    base_p99: float | None = None
    observed_max: float | None = None
    breach_days_current: int | None = None
    breach_days_proposed: int | None = None


def is_recalibration_candidate(metric_key: str, comparison: str, severity: str) -> tuple[bool, str]:
    if comparison != "GreaterThanThreshold":
        return False, "excluded_comparison"
    if severity in EXCLUDED_SEVERITIES:
        return False, "excluded_severity"
    if metric_key not in _POLICY:
        return False, "excluded_metric"
    return True, ""


def _round_threshold(value: float) -> float:
    """표시·알람 이름에 들어가는 값이므로 자릿수를 정리한다 (100↑ 정수, 10↑ 소수 1자리, 그 밖 유효숫자 3)."""
    if value >= 100:
        return float(round(value))
    if value >= 10:
        return round(value, 1)
    return float(f"{value:.3g}")


def propose_threshold(
    *,
    metric_key: str,
    comparison: str,
    current: float,
    severity: str,
    rows: list[dict],
) -> Proposal:
    """단일 시리즈의 제안 계산 (순수 함수). rows = 창 안의 일 단위 스냅샷 행."""
    ok, why = is_recalibration_candidate(metric_key, comparison, severity)
    if not ok:
        return Proposal("excluded", why, current)

    p99s = [float(r["p99"]) for r in rows if r.get("p99") is not None]
    maxes = [float(r["max"]) for r in rows if r.get("max") is not None]
    days = len(p99s)
    if days < MIN_DAYS:
        return Proposal("hold", "insufficient_data", current, days_available=days)

    base = max(p99s)
    observed_max = max(maxes) if maxes else None
    raw = base * HEADROOM
    reasons = ["p99x1.2"]

    _kind, lo, hi = _POLICY[metric_key]
    if lo is not None and raw < lo:
        raw, reasons = lo, reasons + ["clamped_lo"]
    if hi is not None and raw > hi:
        raw, reasons = hi, reasons + ["clamped_hi"]

    if current > 0:
        cap_lo, cap_hi = current * (1 - RATE_CAP), current * (1 + RATE_CAP)
        if raw < cap_lo:
            raw, reasons = cap_lo, reasons + ["rate_capped"]
        elif raw > cap_hi:
            raw, reasons = cap_hi, reasons + ["rate_capped"]

    proposed = _round_threshold(raw)

    def _breach_days(threshold: float) -> int:
        return sum(1 for m in maxes if m > threshold)

    common = dict(
        days_available=days, base_p99=base, observed_max=observed_max,
        breach_days_current=_breach_days(current),
    )
    if current > 0 and abs(proposed - current) / current < HYSTERESIS:
        return Proposal(
            "hold", "hysteresis", current, proposed=current, reasons=reasons + ["hysteresis"],
            breach_days_proposed=_breach_days(current), **common,
        )
    return Proposal(
        "proposed", "p99x1.2", current, proposed=proposed, reasons=reasons,
        breach_days_proposed=_breach_days(proposed), **common,
    )


def _ddb_num(value) -> Decimal:
    return Decimal(str(value))


def _query_series(table, series_id: str, since_iso: str) -> list[dict]:
    rows: list[dict] = []
    kwargs = {
        "KeyConditionExpression": Key("series_id").eq(series_id) & Key("period_start").gte(since_iso),
    }
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return rows


def _proposal_item(entry: dict, proposal: Proposal, *, computed_at: str, ttl: int) -> dict:
    item = {
        "scope_id": f"resource_id:{entry['resource_id']}",
        "metric_key": entry["metric_key"],
        "account_id": entry.get("account_id", ""),
        "resource_type": entry.get("resource_type", ""),
        "status": "shadow",
        "proposal_status": proposal.status,
        "proposal_reasons": proposal.reasons,
        "current_threshold": _ddb_num(proposal.current),
        "window_days": WINDOW_DAYS,
        "days_available": proposal.days_available,
        "computed_at": computed_at,
        "ttl": ttl,
    }
    if proposal.proposed is not None:
        item["proposed_threshold"] = _ddb_num(proposal.proposed)
    if proposal.base_p99 is not None:
        item["base_p99"] = _ddb_num(proposal.base_p99)
    if proposal.observed_max is not None:
        item["observed_max"] = _ddb_num(proposal.observed_max)
    if proposal.breach_days_current is not None:
        item["breach_days_current"] = proposal.breach_days_current
    if proposal.breach_days_proposed is not None:
        item["breach_days_proposed"] = proposal.breach_days_proposed
    return item


def run_shadow_recalibration(accounts: list[dict], *, now: datetime | None = None) -> dict:
    """Shadow 재보정 잡 본체. 결과 통계 dict 반환."""
    hist_name = os.environ.get("METRIC_HISTORY_TABLE")
    ovr_name = os.environ.get("THRESHOLD_OVERRIDES_TABLE")
    if not hist_name or not ovr_name:
        return {"skipped": "missing_table_env"}

    try:
        discovered = discover_resources(accounts)
    except ClientError as e:
        logger.error("discover_resources failed during recalibration: %s", e)
        return {"error": "discover_failed"}
    monitored = [r for r in discovered if r.get("monitoring")]

    now = now or datetime.now(timezone.utc)
    since_iso = (now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    computed_at = now.isoformat(timespec="seconds")
    ttl = int((now + timedelta(days=PROPOSAL_TTL_DAYS)).timestamp())

    ddb = boto3.resource("dynamodb")
    hist_table = ddb.Table(hist_name)
    ovr_table = ddb.Table(ovr_name)

    counts = {
        "resources": len(monitored), "series": 0, "proposed": 0, "hold_hysteresis": 0,
        "insufficient_data": 0, "excluded": 0, "rows_written": 0, "queries": 0,
    }
    items: list[dict] = []
    for resource in monitored:
        for entry in _build_queries_for_resource(resource):
            counts["series"] += 1
            severity = get_severity(entry["metric_key"])
            ok, _why = is_recalibration_candidate(entry["metric_key"], entry.get("comparison", ""), severity)
            if not ok:
                counts["excluded"] += 1
                continue  # 대상이 아니면 DDB 조회도 하지 않는다
            try:
                rows = _query_series(hist_table, entry["series_id"], since_iso)
            except ClientError as e:
                logger.error("MetricHistory query failed for %s: %s", entry["series_id"], e)
                continue
            counts["queries"] += 1
            proposal = propose_threshold(
                metric_key=entry["metric_key"], comparison=entry.get("comparison", ""),
                current=float(entry.get("threshold") or 0), severity=severity, rows=rows,
            )
            if proposal.status == "proposed":
                counts["proposed"] += 1
            elif proposal.reason == "hysteresis":
                counts["hold_hysteresis"] += 1
            elif proposal.reason == "insufficient_data":
                counts["insufficient_data"] += 1
                continue  # 데이터가 쌓이기 전에는 행을 남기지 않는다
            items.append(_proposal_item(entry, proposal, computed_at=computed_at, ttl=ttl))

    try:
        with ovr_table.batch_writer(overwrite_by_pkeys=["scope_id", "metric_key"]) as batch:
            for item in items:
                batch.put_item(Item=item)
                counts["rows_written"] += 1
    except ClientError as e:
        logger.error("Shadow proposal write failed: %s", e)
        counts["error"] = "write_failed"

    logger.info("Shadow recalibration: %s", counts)
    return counts
