"""
/alarms 엔드포인트

GET /alarms          → 알람 목록 (페이지네이션, 상태 필터)
GET /alarms/summary  → 상태별 집계
"""

import json
from datetime import datetime, UTC

from botocore.exceptions import ClientError

from api_handler.cw_helper import list_alarms


def list_alarms_handler(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)
    state_filter = qs.get("state")  # ALARM | OK | INSUFFICIENT_DATA

    try:
        alarms = list_alarms(state_value=state_filter if state_filter else None)
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    items = []
    for alarm in alarms:
        tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
        ts = alarm.get("StateUpdatedTimestamp")
        items.append({
            "id": alarm["AlarmName"],
            "alarm_name": alarm["AlarmName"],
            "resource": _extract_resource_id(alarm["AlarmName"]),
            "type": _extract_resource_type(alarm["AlarmName"]),
            "metric": alarm.get("MetricName", ""),
            "state": alarm.get("StateValue", ""),
            "threshold": alarm.get("Threshold"),
            "severity": tags.get("Severity", "SEV-5"),
            "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts or ""),
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
        all_alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    summary = {"ALARM": 0, "OK": 0, "INSUFFICIENT_DATA": 0}
    for alarm in all_alarms:
        state = alarm.get("StateValue", "")
        if state in summary:
            summary[state] += 1

    return _ok({"total": len(all_alarms), "by_state": summary})


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

import re
_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")


def _extract_resource_id(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(2) if m else alarm_name


def _extract_resource_type(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(1) if m else ""


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
