"""
/alarms 엔드포인트

GET /alarms          → 알람 목록 (페이지네이션, 상태 필터)
GET /alarms/summary  → 상태별 집계
"""

import json
from datetime import datetime, UTC

from botocore.exceptions import ClientError

from api_handler.authz import scope_for
from api_handler.cw_helper import live_alarms
from api_handler.db import scan_all, resource_inventory_table
from common.alarm_builder import resolve_alarm_severity
from common.alarm_identity import identify_alarm
from common.alarm_registry import resource_of_metric


def _customer_alarm_rows(event: dict, qs: dict) -> list[dict]:
    """고객이 직접 만든 알람(우리 메타데이터 없음) — CloudWatch에서 바로 읽는다. 읽기 전용(`source=customer`).

    조회 실패면 빈 목록 — 우리 알람 목록까지 깨지 않게 한다.
    """
    alarms = live_alarms(qs.get("customer_id"), qs.get("account_id"), scope_for(event)) or []
    rows = []
    for a in alarms:
        if identify_alarm(a) is not None:
            continue   # 우리 알람은 인벤토리 행으로 이미 나온다
        rtype, rid = resource_of_metric(a.get("Namespace", ""), a.get("Dimensions") or [])
        updated = a.get("StateUpdatedTimestamp")
        rows.append({
            "entity_type": "alarm",
            "source": "customer",
            "alarm_name": a.get("AlarmName"),
            "arn": a.get("AlarmArn"),
            "account_id": a.get("_account_id"),
            "region": a.get("_region"),
            "resource": rid,
            "type": rtype,
            "metric": a.get("MetricName"),
            "state": a.get("StateValue"),
            "threshold": a.get("Threshold"),
            "severity": resolve_alarm_severity(a),
            "time": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        })
    return rows


def list_alarms_handler(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)
    state_filter = qs.get("state")  # ALARM | OK | INSUFFICIENT_DATA

    try:
        db_items = scan_all(resource_inventory_table())
    except ClientError as e:
        return _err(500, "AWS_ERROR", str(e))

    alarms = [item for item in scope_for(event).filter(db_items) if item.get("entity_type") == "alarm"]
    alarms += _customer_alarm_rows(event, qs)
    if state_filter:
        alarms = [alarm for alarm in alarms if alarm.get("state") == state_filter]

    items = []
    for alarm in alarms:
        threshold_val = alarm.get("threshold")
        if threshold_val is not None:
            try:
                threshold_val = float(threshold_val)
            except ValueError:
                pass
        items.append({
            "id": alarm.get("alarm_name"),
            "alarm_name": alarm.get("alarm_name"),
            "arn": alarm.get("arn"),
            "account": alarm.get("account_id"),
            "resource": alarm.get("resource"),
            "type": alarm.get("type"),
            "metric": alarm.get("metric"),
            "mount_path": alarm.get("mount_path"),
            "state": alarm.get("state"),
            "threshold": threshold_val,
            "severity": alarm.get("severity", "SEV-5"),
            "time": alarm.get("time"),
            "value": None,
            # 고객 알람은 보기만 한다 — 우리가 만들지 않은 알람은 바꾸거나 지우지 않는다
            "source": alarm.get("source", "ours"),
        })

    total = len(items)
    start = (page - 1) * page_size
    return _ok({
        "items": items[start: start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


def get_alarm_summary(event: dict) -> dict:
    try:
        db_items = scan_all(resource_inventory_table())
    except ClientError as e:
        return _err(500, "AWS_ERROR", str(e))

    alarms = [item for item in scope_for(event).filter(db_items) if item.get("entity_type") == "alarm"]
    alarms += _customer_alarm_rows(event, event.get("queryStringParameters") or {})

    summary = {"ALARM": 0, "OK": 0, "INSUFFICIENT_DATA": 0}
    for alarm in alarms:
        state = alarm.get("state", "")
        if state in summary:
            summary[state] += 1

    return _ok({
        "total": len(alarms),
        "by_state": summary,
        "alarm_count": summary["ALARM"],
        "ok_count": summary["OK"],
        "insufficient_count": summary["INSUFFICIENT_DATA"],
    })

# ── 내부 헬퍼 ─────────────────────────────────────────────────────

import re
_DISK_PATH_RE = re.compile(r"disk_used_percent\(([^)]+)\)")


def _alarm_mount_path(alarm: dict) -> str | None:
    if alarm.get("MetricName") != "disk_used_percent":
        return None
    for dim in alarm.get("Dimensions", []):
        if dim.get("Name") == "path" and dim.get("Value"):
            return dim["Value"]
    match = _DISK_PATH_RE.search(alarm.get("AlarmName", ""))
    return match.group(1) if match else None


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
