"""
/accounts 엔드포인트

GET    /accounts                  → 어카운트 목록 (?customer_id=X)
POST   /accounts                  → 어카운트 생성
DELETE /accounts/{id}             → 어카운트 삭제
POST   /accounts/{id}/test        → AWS 연결 테스트 (STS AssumeRole)
"""

import functools
import json
import logging
import os
from datetime import datetime, UTC

import boto3
from botocore.exceptions import ClientError

from api_handler.db import accounts_table, scan_all, query_by_pk

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _current_account_id() -> str:
    return boto3.client("sts").get_caller_identity().get("Account", "")


@functools.lru_cache(maxsize=1)
def _events_client():
    return boto3.client("events")


def _forward_statement_id(account_id: str) -> str:
    return f"acct-{account_id}"


def _grant_alert_forwarding(account_id: str) -> str:
    """등록된 계정이 알림 이벤트 버스로 알람 이벤트를 보낼 수 있게 PutEvents 권한을 준다.

    버스 정책이 없으면 고객사 계정의 전달 룰이 조용히 막힌다(교차계정 PutEvents는 발신 룰의
    역할 + 수신 버스의 정책 둘 다 필요). 실패해도 등록 자체는 성공시키되 상태를 남겨 드러낸다 —
    조용히 삼키면 온보딩 후 "이벤트가 안 온다"의 원인이 감춰진다.
    """
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus or not account_id:
        return "skipped"
    if account_id == _current_account_id():
        return "self"     # 우리 계정은 기본 버스 룰로 들어온다 — 교차계정 정책 불필요
    try:
        _events_client().put_permission(
            EventBusName=bus, Action="events:PutEvents",
            Principal=account_id, StatementId=_forward_statement_id(account_id))
        return "granted"
    except ClientError as e:
        logger.error("Failed to grant alert forwarding to %s on bus %s: %s", account_id, bus, e)
        return "grant_failed"


def _revoke_alert_forwarding_if_orphan(account_id: str) -> None:
    """다른 고객사 행이 이 계정을 더 쓰지 않을 때만 버스 권한을 회수한다."""
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus or not account_id or account_id == _current_account_id():
        return
    try:
        remaining = scan_all(accounts_table())
    except ClientError as e:
        logger.warning("Could not check remaining accounts before revoke of %s: %s", account_id, e)
        return
    if any((a.get("account_id") or "") == account_id for a in remaining):
        return
    try:
        _events_client().remove_permission(
            EventBusName=bus, StatementId=_forward_statement_id(account_id))
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return
        logger.warning("Failed to revoke alert forwarding for %s on bus %s: %s", account_id, bus, e)


def list_accounts(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    try:
        if customer_id:
            items = query_by_pk(accounts_table(), "customer_id", customer_id)
        else:
            items = scan_all(accounts_table())
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return _ok(items)


def create_account(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")

    required = ("account_id", "role_arn", "name", "customer_id")
    missing = [f for f in required if not (body.get(f) or "").strip()]
    if missing:
        return _err(400, "VALIDATION_ERROR", f"필수 필드 누락: {', '.join(missing)}")

    account_id = body["account_id"].strip()
    customer_id = body["customer_id"].strip()

    table = accounts_table()
    try:
        existing = table.get_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        ).get("Item")
        if existing:
            return _err(409, "DUPLICATE", f"account_id '{account_id}'가 이미 존재합니다")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    regions = _normalize_regions(body.get("regions"))
    if not regions:
        return _err(400, "VALIDATION_ERROR", "regions must include at least one AWS region")

    item = {
        "customer_id": customer_id,
        "account_id": account_id,
        "name": body["name"].strip(),
        "role_arn": body["role_arn"].strip(),
        "regions": regions,
        "connection_status": "untested",
        "created_at": datetime.now(UTC).isoformat(),
    }
    item["alert_forwarding"] = _grant_alert_forwarding(account_id)
    try:
        table.put_item(Item=item)
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return _ok(item, status=201)


def delete_account(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    account_id = path_params.get("id", "").strip()
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    if not account_id or not customer_id:
        return _err(400, "MISSING_PARAM", "account_id와 customer_id가 필요합니다")

    try:
        accounts_table().delete_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        )
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    _revoke_alert_forwarding_if_orphan(account_id)
    return {"statusCode": 204, "body": ""}


def test_connection(event: dict) -> dict:
    """STS AssumeRole로 실제 AWS 연결 가능 여부를 확인한다."""
    path_params = event.get("pathParameters") or {}
    account_id = path_params.get("id", "").strip()
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    if not account_id or not customer_id:
        return _err(400, "MISSING_PARAM", "account_id와 customer_id가 필요합니다")

    table = accounts_table()
    try:
        item = table.get_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        ).get("Item")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    if not item:
        return _err(404, "NOT_FOUND", "어카운트를 찾을 수 없습니다")

    role_arn = item.get("role_arn", "")
    if not role_arn:
        return _err(400, "MISSING_ROLE", "role_arn이 설정되지 않았습니다")

    try:
        session_kwargs = _assume_role_kwargs(item)
        regions = item.get("regions") or []
        region_results = [
            _test_region_access(region, session_kwargs)
            for region in regions
        ]
        status = "connected" if regions and all(r["status"] == "connected" for r in region_results) else "failed"
        error_msg = next((r.get("error") for r in region_results if r["status"] == "failed"), None)
    except ClientError as e:
        status = "failed"
        error_msg = str(e)
        region_results = [
            {"region": region, "status": "failed", "error": error_msg}
            for region in (item.get("regions") or [])
        ]

    # 연결 상태 업데이트
    try:
        table.update_item(
            Key={"customer_id": customer_id, "account_id": account_id},
            UpdateExpression="SET connection_status = :s, last_tested_at = :t",
            ExpressionAttributeValues={
                ":s": status,
                ":t": datetime.now(UTC).isoformat(),
            },
        )
    except ClientError:
        pass  # 상태 업데이트 실패는 무시

    result = {
        "account_id": account_id,
        "status": status,
        "regions": region_results,
        "tested_at": datetime.now(UTC).isoformat(),
    }
    if error_msg:
        result["error"] = error_msg
    return _ok(result)


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}


def _normalize_regions(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(region).strip() for region in value if str(region).strip()]


def _assume_role_kwargs(account: dict) -> dict:
    if account.get("account_id", "") == _current_account_id():
        return {}

    resp = boto3.client("sts").assume_role(
        RoleArn=account.get("role_arn", ""),
        RoleSessionName="ConnectionTest",
    )
    creds = resp["Credentials"]
    return {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
    }


def _test_region_access(region: str, session_kwargs: dict) -> dict:
    try:
        cw = boto3.client("cloudwatch", region_name=region, **session_kwargs)
        cw.describe_alarms(MaxRecords=1)
        return {"region": region, "status": "connected"}
    except ClientError as e:
        return {"region": region, "status": "failed", "error": str(e)}
