"""
/dashboard 엔드포인트

GET /dashboard/stats          → 통계 카드 4개
GET /dashboard/recent-alarms  → 최근 알람 트리거 목록
"""

import json
from datetime import datetime, UTC

from botocore.exceptions import ClientError

from api_handler.cw_helper import get_dashboard_stats


def get_stats(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id")
    account_id = qs.get("account_id")

    try:
        stats = get_dashboard_stats(customer_id, account_id)
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    return _ok(stats)


def get_recent_alarms(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 10)), 50)

    try:
        from api_handler.db import scan_all, resource_inventory_table
        db_items = scan_all(resource_inventory_table())
    except ClientError as e:
        return _err(500, "AWS_ERROR", str(e))

    alarms = [
        item for item in db_items
        if item.get("entity_type") == "alarm" and item.get("state") == "ALARM"
    ]

    items = []
    for alarm in alarms:
        threshold_val = alarm.get("threshold")
        if threshold_val is not None:
            try:
                threshold_val = float(threshold_val)
            except ValueError:
                pass
        items.append({
            "timestamp": alarm.get("time"),
            "alarm_name": alarm.get("alarm_name"),
            "resource": alarm.get("resource"),
            "type": alarm.get("type"),
            "metric": alarm.get("metric"),
            "state": alarm.get("state"),
            "threshold": threshold_val,
            "severity": alarm.get("severity", "SEV-5"),
        })

    items.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    total = len(items)
    start = (page - 1) * page_size

    return _ok({
        "items": items[start: start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


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
