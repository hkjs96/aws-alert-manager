"""
/customers 엔드포인트

GET    /customers          → 전체 고객사 목록
POST   /customers          → 고객사 생성
PUT    /customers/{id}     → 이름·담당자(managers) 편집 — 관리자 또는 그 고객사 담당자
DELETE /customers/{id}     → 고객사 삭제 (관리자 전용)

범위: docs/specs/authz-scoping/design.md — 목록은 범위로 거르고, 범위 밖 편집은 404.
"""

import json
import uuid
from datetime import datetime, UTC

from botocore.exceptions import ClientError

from api_handler.authz import normalize_managers, scope_for
from api_handler.db import customers_table, query_by_pk, accounts_table


def list_customers(event: dict) -> dict:
    from api_handler.db import scan_all
    try:
        items = scan_all(customers_table())
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))
    items = scope_for(event).filter(items)
    for item in items:
        item["managers"] = normalize_managers(item.get("managers"))

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

    from api_handler.identity import current_email
    email = current_email(event)
    item = {
        "customer_id": code,
        "name": name,
        "provider": body.get("provider", "aws"),
        "account_count": 0,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if email:
        # 만든 사람이 자동 담당자 — 일반 사용자는 이것 없이는 방금 만든 고객사를 볼 수 없다.
        item["managers"] = [email]
    try:
        table.put_item(Item=item)
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    # 생성자가 만든 고객사를 자기 뷰에 자동 포함 (best-effort)
    from api_handler.routes.preferences import add_owned_customer
    if email:
        try:
            add_owned_customer(email, code)
        except ClientError:
            pass  # 선택 추가 실패해도 생성 자체는 성공

    return _ok(item, status=201)


def update_customer(event: dict) -> dict:
    """이름·담당자 편집. 관리자 또는 현재 담당자만 — 그 밖에는 404(존재를 흘리지 않는다).

    담당자 목록은 비울 수 없다 — 비우면 관리자 말고는 아무도 못 보는 고아 고객사가 된다.
    """
    customer_id = (event.get("pathParameters") or {}).get("id", "")
    if not customer_id:
        return _err(400, "MISSING_PARAM", "customer_id가 필요합니다")
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")
    if not isinstance(body, dict):
        return _err(400, "INVALID_JSON", "요청 본문이 객체가 아닙니다")

    scope = scope_for(event)
    table = customers_table()
    try:
        item = table.get_item(Key={"customer_id": customer_id}).get("Item")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))
    if not item:
        return _err(404, "NOT_FOUND", "고객사를 찾을 수 없습니다")
    # scope.customer_ids는 요청 시점의 managers로 계산되지만, 방금 읽은 행으로 한 번 더 본다.
    if not scope.unrestricted and scope.email not in normalize_managers(item.get("managers")):
        return _err(404, "NOT_FOUND", "고객사를 찾을 수 없습니다")

    updated = dict(item)
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            return _err(400, "VALIDATION_ERROR", "name은 비울 수 없습니다")
        updated["name"] = name
    if "managers" in body:
        if not isinstance(body["managers"], list):
            return _err(400, "VALIDATION_ERROR", "managers는 이메일 목록이어야 합니다")
        managers = normalize_managers(body["managers"])
        if not managers:
            return _err(400, "VALIDATION_ERROR", "담당자는 한 명 이상이어야 합니다")
        updated["managers"] = managers
    if "name" not in body and "managers" not in body:
        return _err(400, "VALIDATION_ERROR", "name 또는 managers가 필요합니다")
    if not normalize_managers(updated.get("managers")):
        return _err(400, "VALIDATION_ERROR", "담당자는 한 명 이상이어야 합니다")
    updated["updated_at"] = datetime.now(UTC).isoformat()

    try:
        table.put_item(Item=updated)
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))
    return _ok(updated)


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
