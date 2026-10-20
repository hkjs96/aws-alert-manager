"""
/me 엔드포인트 — 로그인 사용자 신원 + 개인 뷰 선택(담당 고객사).

GET /me                 → {email, is_admin, owned_customer_ids}
PUT /me/preferences     → owned_customer_ids 저장

owned_customer_ids 는 접근 제어가 아니라 **개인 뷰 필터**다(대시보드/리소스/
알람에서 볼 고객사 선택). 신원은 JWT authorizer가 검증한 이메일.
"""

import json

from botocore.exceptions import ClientError

from api_handler.db import user_preferences_table
from api_handler.identity import current_email, is_admin


def _load_owned(email: str) -> list[str]:
    item = user_preferences_table().get_item(Key={"user_email": email}).get("Item")
    if not item:
        return []
    ids = item.get("owned_customer_ids", [])
    return [str(x) for x in ids] if isinstance(ids, list) else []


def add_owned_customer(email: str, customer_id: str) -> None:
    """customer_id 를 사용자의 담당 목록에 추가(멱등). customers.create에서 호출."""
    current = _load_owned(email)
    if customer_id in current:
        return
    user_preferences_table().put_item(
        Item={"user_email": email, "owned_customer_ids": [*current, customer_id]}
    )


def get_me(event: dict) -> dict:
    """`owned_customer_ids` = 이 사용자가 **볼 수 있는** 고객사(2026-10-20, docs/specs/authz-scoping).

    예전에는 사용자가 체크한 개인 화면 필터였다. 이제 접근 권한이 고객사 `managers`로 정해지므로 화면 필터를 같은 범위로
    맞춘다 — 일반 사용자는 담당 고객사, 관리자(제한 없음)는 전체. 화면은 이 목록으로 필터하므로 백엔드 범위와 어긋나지 않는다.
    """
    from api_handler.authz import scope_for
    from api_handler.db import customers_table, scan_all

    email = current_email(event)
    scope = scope_for(event)
    if scope.unrestricted:
        try:
            owned = sorted(c["customer_id"] for c in scan_all(customers_table()))
        except (ClientError, KeyError):   # 표가 없는 환경(로컬·테스트) — 예전 개인 목록으로
            owned = _load_owned(email) if email else []
    else:
        owned = sorted(scope.customer_ids)
    return _ok({
        "email": email,
        "is_admin": is_admin(email),
        "owned_customer_ids": owned,
    })


def put_preferences(event: dict) -> dict:
    email = current_email(event)
    if not email:
        return _err(401, "NO_IDENTITY", "로그인이 필요합니다")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")

    ids = body.get("owned_customer_ids")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return _err(400, "VALIDATION_ERROR", "owned_customer_ids must be a list of strings")

    # 중복 제거(순서 유지)
    deduped = list(dict.fromkeys(ids))
    try:
        user_preferences_table().put_item(
            Item={"user_email": email, "owned_customer_ids": deduped}
        )
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return _ok({"owned_customer_ids": deduped})


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
