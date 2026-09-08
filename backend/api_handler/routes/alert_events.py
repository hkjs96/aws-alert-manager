"""
/alert/events 엔드포인트 (review-personas F7)

GET /alert/events → 알람 이벤트별 **알림 처리 결과**와 그 사유.

"알람은 울렸는데 왜 안 왔지"에 답하는 화면의 데이터원이다. 억제 판정은 지금까지 이력 테이블과
로그에만 있어 고객이 볼 수 없었다 — Phase 2에서 발송이 시작되면 첫 문의가 이것이다.

판정과 문구는 `common.alert_verdict`가 정본이다(억제율 리포트와 같은 규칙). 프런트가
`dedup` 같은 토큰을 각자 번역하면 화면마다 말이 갈린다.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from api_handler.db import alert_state_table, customers_table, event_history_table, scan_all
from common.alert_verdict import NOTIFY, PENDING, SUPPRESS, kind, verdict

logger = logging.getLogger(__name__)

#: 이력은 90일 보관이지만 한 번에 훑는 범위는 제한한다 — GSI 쿼리가 (고객사 × 일) 수만큼 나간다.
MAX_DAYS = 14
DEFAULT_DAYS = 1
MAX_LIMIT = 500
DEFAULT_LIMIT = 100

#: 격리 종료 시각을 함께 보여줄 사유. "언제까지 조용한가"가 진짜 궁금한 정보다.
_QUARANTINE_REASONS = ("flapping",)

_FIELDS = (
    "occurred_at", "series_id", "event_key", "customer_id", "account_id", "region",
    "alarm_name", "resource_id", "resource_type", "metric_key", "severity",
    "state", "previous_state", "state_reason", "group_id", "finalized_at",
)


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str, ensure_ascii=False)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status,
            "body": json.dumps({"code": code, "message": message}, ensure_ascii=False)}


def _int_param(qs: dict, name: str, default: int, lo: int, hi: int) -> int:
    raw = str(qs.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return default


def _customer_ids(explicit: str) -> list[str]:
    """조회 대상 고객사. 지정이 없으면 등록된 고객사 전부 + 미매핑(빈 문자열) 파티션."""
    if explicit:
        return [explicit]
    try:
        ids = [str(c.get("customer_id", "") or "") for c in scan_all(customers_table())]
    except ClientError as e:
        logger.error("customer list failed: %s", e)
        raise
    # 고객사 매핑이 없는 계정의 이벤트는 `#YYYY-MM-DD` 파티션에 쌓인다 — 빠뜨리면
    # 미등록 계정 알람이 화면에서 통째로 사라진다(review-personas F5와 같은 뿌리).
    return sorted({*(i for i in ids if i), ""})


def _query_day(table, customer_id: str, day: str) -> list[dict]:
    items: list[dict] = []
    kwargs = {
        "IndexName": "customer_day-index",
        "KeyConditionExpression": Key("customer_day").eq(f"{customer_id}#{day}"),
        "ScanIndexForward": False,      # 최신 이벤트부터
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def _quarantine_until(series_ids: list[str]) -> dict[str, str]:
    """격리 중인 지문의 해제 시각. 상태 테이블이 없거나 실패해도 조회는 계속한다."""
    name = os.environ.get("ALERT_STATE_TABLE", "")
    if not name or not series_ids:
        return {}
    table = alert_state_table()
    out: dict[str, str] = {}
    for sid in series_ids:
        try:
            item = table.get_item(Key={"state_key": f"fp#{sid}"}).get("Item") or {}
        except ClientError as e:
            logger.warning("state read failed for %s: %s", sid, e)
            continue
        until = str(item.get("quarantined_until", "") or "")
        if until:
            out[sid] = until
    return out


def _row(item: dict) -> dict:
    row = {f: str(item.get(f, "") or "") for f in _FIELDS}
    row["kind"] = kind(item)
    row.update(verdict(item))
    row["suppressed"] = bool(item.get("suppressed"))
    row["finalized"] = bool(item.get("final_action"))
    if item.get("parse_error"):
        row["parse_error"] = str(item["parse_error"])
    return row


def list_events(event: dict) -> dict:
    """기간 안의 알람 이벤트와 그 처리 결과."""
    qs = event.get("queryStringParameters") or {}
    days = _int_param(qs, "days", DEFAULT_DAYS, 1, MAX_DAYS)
    limit = _int_param(qs, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    customer_id = str(qs.get("customer_id", "") or "").strip()
    resource_id = str(qs.get("resource_id", "") or "").strip()
    action_filter = str(qs.get("action", "") or "").strip().lower()
    if action_filter and action_filter not in (NOTIFY, SUPPRESS, PENDING):
        return _err(400, "VALIDATION_ERROR",
                    f"action은 {NOTIFY}/{SUPPRESS}/{PENDING} 중 하나여야 합니다")

    if not os.environ.get("EVENT_HISTORY_TABLE", ""):
        return _err(503, "NOT_CONFIGURED", "이벤트 이력 테이블이 설정되지 않았습니다")

    today = datetime.now(timezone.utc).date()
    day_list = [(today - timedelta(days=d)).isoformat() for d in range(days)]

    try:
        customers = _customer_ids(customer_id)
    except ClientError:
        return _err(503, "STORAGE_ERROR", "고객사 목록을 읽지 못했습니다")

    table = event_history_table()
    items: list[dict] = []
    try:
        for cid in customers:
            for day in day_list:
                items.extend(_query_day(table, cid, day))
    except ClientError as e:
        logger.error("event history query failed: %s", e)
        return _err(503, "STORAGE_ERROR", "이벤트 이력을 읽지 못했습니다")

    rows = [_row(i) for i in items]
    if resource_id:
        rows = [r for r in rows if r["resource_id"] == resource_id]

    # 집계는 **필터 적용 후, 건수 제한 전** 값이다 — 화면의 요약이 목록의 일부만 세면 안 된다.
    summary = {"total": len(rows), NOTIFY: 0, SUPPRESS: 0, PENDING: 0, "config": 0}
    for r in rows:
        if r["kind"] == "config":
            summary["config"] += 1
        summary[r["action"]] = summary.get(r["action"], 0) + 1
    decided = summary[NOTIFY] + summary[SUPPRESS]
    summary["suppression_rate"] = round(summary[SUPPRESS] / decided, 4) if decided else 0.0

    if action_filter:
        rows = [r for r in rows if r["action"] == action_filter]

    rows.sort(key=lambda r: (r["occurred_at"], r["event_key"]), reverse=True)
    truncated = len(rows) > limit
    rows = rows[:limit]

    quarantined = _quarantine_until(
        sorted({r["series_id"] for r in rows if r["reason"] in _QUARANTINE_REASONS}))
    for r in rows:
        until = quarantined.get(r["series_id"])
        if until:
            r["quarantined_until"] = until

    return _ok({
        "events": rows,
        "summary": summary,
        "days": days,
        "truncated": truncated,
        "limit": limit,
    })
