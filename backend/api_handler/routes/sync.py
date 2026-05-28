"""
/sync endpoints.
"""

import functools
import json
import os
import uuid
from datetime import datetime, UTC

import boto3
from botocore.exceptions import ClientError

from api_handler.db import accounts_table, job_status_table, scan_all

DEFAULT_REGION = "ap-northeast-2"


@functools.lru_cache(maxsize=1)
def _lambda_client():
    return boto3.client("lambda")


def import_alarms(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "BAD_REQUEST", "JSON parse error")

    scope = _normalize_scope(body.get("scope") or {})
    try:
        target_count = _target_account_count(scope)
    except ClientError as exc:
        return _err(500, "DB_ERROR", str(exc))

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    try:
        job_status_table().put_item(Item={
            "job_id": job_id,
            "status": "pending",
            "target": "alarms",
            "scope": scope,
            "total_count": target_count,
            "completed_count": 0,
            "failed_count": 0,
            "results": [],
            "created_at": now,
            "updated_at": now,
        })
        _lambda_client().invoke(
            FunctionName=os.environ["DAILY_MONITOR_FUNCTION_NAME"],
            InvocationType="Event",
            Payload=json.dumps({
                "sync_target": "alarms",
                "sync_job_id": job_id,
                "scope": scope,
            }).encode("utf-8"),
        )
    except ClientError as exc:
        return _err(500, "SYNC_ERROR", str(exc))
    except KeyError:
        return _err(500, "CONFIG_ERROR", "DAILY_MONITOR_FUNCTION_NAME is not configured")

    return _ok({"job_id": job_id, "status": "pending", "total_count": target_count}, status=202)


def _normalize_scope(scope: dict) -> dict:
    customer_id = str(scope.get("customer_id") or "").strip()
    account_id = str(scope.get("account_id") or "").strip()
    regions = _normalize_regions(scope.get("regions"))
    return {
        "customer_id": customer_id,
        "account_id": account_id,
        "regions": regions or [DEFAULT_REGION],
    }


def _normalize_regions(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)
    return [str(region).strip() for region in values if str(region).strip()]


def _target_account_count(scope: dict) -> int:
    accounts = scan_all(accounts_table())
    if scope.get("customer_id"):
        accounts = [acc for acc in accounts if acc.get("customer_id") == scope["customer_id"]]
    if scope.get("account_id"):
        accounts = [acc for acc in accounts if acc.get("account_id") == scope["account_id"]]
    return max(len(accounts), 1)


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
