"""
api_handler 인증 allowlist 가드(_authorize) 단위 테스트

검증 범위:
- allowlist 미설정 → 무제한 통과
- 개인 이메일 allowlist 매칭
- 도메인 allowlist 매칭 (email 도메인 / Workspace hd 클레임)
- 미허용 이메일 거부 (403)
- 미검증/누락 신원 거부
- /health 는 allowlist 설정과 무관하게 통과 (라우터 우회)
- 거부는 라우트 핸들러 실행 전에 일어남 (DB 미접근)
"""

import json

import pytest


def _event(method: str, path: str, *, email=None, hd=None, email_verified="true") -> dict:
    """JWT authorizer claims 를 포함한 API Gateway HTTP API v2 이벤트."""
    claims = {}
    if email is not None:
        claims["email"] = email
        claims["email_verified"] = email_verified
    if hd is not None:
        claims["hd"] = hd
    return {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": claims}},
        },
        "rawPath": path,
        "queryStringParameters": {},
        "pathParameters": {},
        "body": None,
    }


# ── _authorize 직접 단위 테스트 ─────────────────────────────────────


def test_no_allowlist_passes_through(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("ALLOWED_EMAIL_DOMAINS", raising=False)
    assert _authorize(_event("GET", "/customers")) is None


def test_personal_email_allowed(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAILS", "me@gmail.com")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "")
    assert _authorize(_event("GET", "/customers", email="ME@gmail.com")) is None


def test_company_domain_allowed_via_email(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAILS", "")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    assert _authorize(_event("GET", "/customers", email="alice@company.com")) is None


def test_company_domain_allowed_via_hd_claim(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    # email 도메인은 다르지만 Workspace hd 클레임이 매칭
    ev = _event("GET", "/customers", email="alice@alias.example", hd="company.com")
    assert _authorize(ev) is None


def test_other_email_denied(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAILS", "me@gmail.com")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    resp = _authorize(_event("GET", "/customers", email="stranger@evil.com"))
    assert resp is not None and resp["statusCode"] == 403
    assert json.loads(resp["body"])["code"] == "FORBIDDEN"


def test_missing_identity_denied_when_allowlist_set(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    resp = _authorize(_event("GET", "/customers"))  # no claims
    assert resp is not None and resp["statusCode"] == 403


def test_unverified_email_denied(monkeypatch):
    from api_handler.lambda_handler import _authorize
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    ev = _event("GET", "/customers", email="alice@company.com", email_verified="false")
    resp = _authorize(ev)
    assert resp is not None and resp["statusCode"] == 403


# ── 라우터 통합: 가드 배치/우회 ─────────────────────────────────────


def test_health_exempt_from_allowlist(monkeypatch):
    """allowlist 가 설정돼도 /health 는 신원 없이 통과한다."""
    from api_handler.lambda_handler import lambda_handler
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    resp = lambda_handler(_event("GET", "/health"), None)
    assert resp["statusCode"] == 200


def test_denied_before_route_handler(monkeypatch):
    """거부는 라우트 핸들러(DB 접근) 실행 전에 일어나야 한다."""
    from api_handler.lambda_handler import lambda_handler
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "company.com")
    # /customers 매칭되지만 미허용 신원 → 403, 핸들러 미실행
    resp = lambda_handler(_event("GET", "/customers", email="x@evil.com"), None)
    assert resp["statusCode"] == 403
    assert "Access-Control-Allow-Origin" in resp["headers"]
