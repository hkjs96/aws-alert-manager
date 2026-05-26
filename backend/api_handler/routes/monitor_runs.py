"""
/monitor-runs endpoints.

GET /monitor-runs  - recent DailyMonitor execution records
"""

import json
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

    items = [_json_safe(item) for item in resp.get("Items", [])]
    return {
        "statusCode": 200,
        "body": json.dumps({
            "items": items,
            "count": len(items),
            "limit": limit,
            "next_key": _json_safe(resp.get("LastEvaluatedKey")),
        }),
    }


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
