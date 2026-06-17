"""
/customers 엔드포인트

GET    /customers          → 전체 고객사 목록
POST   /customers          → 고객사 생성
DELETE /customers/{id}     → 고객사 삭제
"""

import json
import uuid
from datetime import datetime, UTC

from botocore.exceptions import ClientError

from api_handler.db import customers_table, query_by_pk, accounts_table


def list_customers(event: dict) -> dict:
    from api_handler.db import scan_all
    try:
        items = scan_all(customers_table())
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    # account_count 보정 (AccountsTable에서 집계)
    try:
        accounts = scan_all(accounts_table())
        count_map: dict[str, int] = {}
        for acc in accounts:
            cid = acc.get("customer_id", "")
            count_map[cid] = count_map.get(cid, 0) + 1
        for item in items:
            item["account_count"] = count_map.get(item["customer_id"], 0)
    except ClientError:
        pass  # account_count 없어도 목록 반환

    return _ok(items)


def create_customer(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")

    name = (body.get("name") or "").strip()
    code = (body.get("code") or "").strip()
    if not name or not code:
        return _err(400, "VALIDATION_ERROR", "name과 code는 필수입니다")

    table = customers_table()
    # 중복 체크
    try:
        existing = table.get_item(Key={"customer_id": code}).get("Item")
        if existing:
            return _err(409, "DUPLICATE", f"customer_id '{code}'가 이미 존재합니다")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    item = {
        "customer_id": code,
        "name": name,
        "provider": body.get("provider", "aws"),
        "account_count": 0,
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        table.put_item(Item=item)
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    # 생성자가 만든 고객사를 자기 뷰에 자동 포함 (best-effort)
    from api_handler.identity import current_email
    from api_handler.routes.preferences import add_owned_customer
    email = current_email(event)
    if email:
        try:
            add_owned_customer(email, code)
        except ClientError:
            pass  # 선택 추가 실패해도 생성 자체는 성공

    return _ok(item, status=201)


def delete_customer(event: dict) -> dict:
    from api_handler.identity import current_email, is_admin, admin_enforced
    if admin_enforced() and not is_admin(current_email(event)):
        return _err(403, "FORBIDDEN", "고객사 삭제 권한이 없습니다 (관리자 전용)")

    customer_id = (event.get("pathParameters") or {}).get("id", "")
    if not customer_id:
        return _err(400, "MISSING_PARAM", "customer_id가 필요합니다")

    try:
        customers_table().delete_item(Key={"customer_id": customer_id})
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return {"statusCode": 204, "body": ""}


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
