"""
요청 신원(이메일) + admin 판별 헬퍼.

이메일은 API Gateway JWT authorizer가 검증한 claims에서 가져온다(서명·만료·
audience 검증 완료). 인증이 꺼진 환경(authorizer 없음)에서는 빈 문자열.
"""

import os


def current_email(event: dict) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    ) or {}
    return str(claims.get("email", "")).strip().lower()


def _admin_set() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(email: str) -> bool:
    return bool(email) and email in _admin_set()


def admin_enforced() -> bool:
    """ADMIN_EMAILS가 설정된 경우에만 admin 제한을 강제한다.
    미설정(빈 값)이면 admin 미적용 — 로컬/미구성 환경에서 동작 유지."""
    return bool(_admin_set())
