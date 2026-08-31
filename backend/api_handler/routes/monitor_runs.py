"""
/monitor-runs endpoints.

GET /monitor-runs  - recent DailyMonitor execution records
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from api_handler.db import monitor_run_history_table


def list_monitor_runs(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    limit = _parse_limit(qs.get("limit"))

    try:
        resp = monitor_run_history_table().query(
            KeyConditionExpression=Key("scope").eq("daily_monitor"),
            ScanIndexForward=False,
            Limit=limit,
        )
    except ClientError as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"code": "DDB_ERROR", "message": str(e)}),
        }

    items = _with_derived_status([_json_safe(item) for item in resp.get("Items", [])])
    return {
        "statusCode": 200,
        "body": json.dumps({
            "items": items,
            "count": len(items),
            "limit": limit,
            "next_key": _json_safe(resp.get("LastEvaluatedKey")),
        }),
    }


# 워커 타임아웃(900s)보다 넉넉한 값 — daily_monitor._STALE_RUN_AFTER_SECONDS와 동일 기준.
_STALE_RUN_AFTER_SECONDS = 20 * 60


def _with_derived_status(items: list[dict], now: datetime | None = None) -> list[dict]:
    """finish 기록 없이 오래 running인 run은 timeout으로 표시한다.

    워커가 타임아웃되면 레코드가 running으로 남는다. 워커는 다음 run 시작 시 이를
    영속 정정하지만, 그 전까지 UI에 유령 running이 보이지 않도록 조회 시점에도
    같은 규칙으로 파생 상태를 계산한다(저장하지 않음, stale=True로 표시).
    """
    now = now or datetime.now(timezone.utc)
    for item in items:
        if item.get("status") != "running":
            continue
        started = _parse_iso(item.get("started_at"))
        if started and (now - started).total_seconds() > _STALE_RUN_AFTER_SECONDS:
            item["status"] = "timeout"
            item["stale"] = True
    return items


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_limit(raw) -> int:
    try:
        value = int(raw or 50)
    except (TypeError, ValueError):
        return 50
    return max(1, min(value, 100))


def _json_safe(value):
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    return value
