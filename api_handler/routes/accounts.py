"""
/accounts 엔드포인트

GET    /accounts                  → 어카운트 목록 (?customer_id=X)
POST   /accounts                  → 어카운트 생성
DELETE /accounts/{id}             → 어카운트 삭제
POST   /accounts/{id}/test        → AWS 연결 테스트 (STS AssumeRole)
"""

import json
from datetime import datetime, UTC

import boto3
from botocore.exceptions import ClientError

from api_handler.db import accounts_table, scan_all, query_by_pk


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

    item = {
        "customer_id": customer_id,
        "account_id": account_id,
        "name": body["name"].strip(),
        "role_arn": body["role_arn"].strip(),
        "regions": body.get("regions", ["ap-northeast-2"]),
        "connection_status": "untested",
        "created_at": datetime.now(UTC).isoformat(),
    }
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

    sts = boto3.client("sts")
    try:
        sts.assume_role(RoleArn=role_arn, RoleSessionName="ConnectionTest")
        status = "connected"
        error_msg = None
    except ClientError as e:
        status = "failed"
        error_msg = str(e)

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

    result = {"account_id": account_id, "status": status}
    if error_msg:
        result["error"] = error_msg
    return _ok(result)


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
