"""
/me 개인 뷰 선택(preferences) + 고객사 삭제 admin 가드 단위 테스트
"""

import json
from unittest.mock import MagicMock

import pytest


def _event(method: str, path: str, *, email=None, body=None, path_params=None) -> dict:
    claims = {"email": email} if email is not None else {}
    return {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": claims}},
        },
        "rawPath": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
    }


@pytest.fixture
def prefs_table(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr("api_handler.routes.preferences.user_preferences_table", lambda: table)
    return table


# ── GET /me ─────────────────────────────────────────────────────────


def test_get_me_admin_with_owned(monkeypatch, prefs_table):
    from api_handler.routes.preferences import get_me
    monkeypatch.setenv("ADMIN_EMAILS", "boss@mz.co.kr")
    prefs_table.get_item.return_value = {"Item": {"owned_customer_ids": ["c1", "c2"]}}
    resp = get_me(_event("GET", "/me", email="BOSS@mz.co.kr"))
    body = json.loads(resp["body"])
    assert body["email"] == "boss@mz.co.kr"
    assert body["is_admin"] is True
    assert body["owned_customer_ids"] == ["c1", "c2"]


def test_get_me_non_admin(monkeypatch, prefs_table):
    from api_handler.routes.preferences import get_me
    monkeypatch.setenv("ADMIN_EMAILS", "boss@mz.co.kr")
    resp = get_me(_event("GET", "/me", email="member@mz.co.kr"))
    body = json.loads(resp["body"])
    assert body["is_admin"] is False
    assert body["owned_customer_ids"] == []


def test_get_me_no_identity(prefs_table):
    from api_handler.routes.preferences import get_me
    resp = get_me(_event("GET", "/me"))
    body = json.loads(resp["body"])
    assert body["email"] == ""
    assert body["is_admin"] is False
    assert body["owned_customer_ids"] == []


# ── PUT /me/preferences ─────────────────────────────────────────────


def test_put_preferences_saves_deduped(prefs_table):
    from api_handler.routes.preferences import put_preferences
    resp = put_preferences(
        _event("PUT", "/me/preferences", email="m@mz.co.kr",
               body={"owned_customer_ids": ["c1", "c2", "c1"]})
    )
    assert resp["statusCode"] == 200
    saved = prefs_table.put_item.call_args.kwargs["Item"]
    assert saved["user_email"] == "m@mz.co.kr"
    assert saved["owned_customer_ids"] == ["c1", "c2"]


def test_put_preferences_no_identity(prefs_table):
    from api_handler.routes.preferences import put_preferences
    resp = put_preferences(_event("PUT", "/me/preferences", body={"owned_customer_ids": []}))
    assert resp["statusCode"] == 401


def test_put_preferences_invalid_body(prefs_table):
    from api_handler.routes.preferences import put_preferences
    resp = put_preferences(
        _event("PUT", "/me/preferences", email="m@mz.co.kr", body={"owned_customer_ids": "nope"})
    )
    assert resp["statusCode"] == 400


# ── DELETE /customers/{id} admin 가드 ───────────────────────────────


def test_delete_customer_non_admin_403(monkeypatch):
    from api_handler.routes.customers import delete_customer
    monkeypatch.setenv("ADMIN_EMAILS", "boss@mz.co.kr")
    table = MagicMock()
    monkeypatch.setattr("api_handler.routes.customers.customers_table", lambda: table)
    resp = delete_customer(_event("DELETE", "/customers/c1", email="member@mz.co.kr",
                                  path_params={"id": "c1"}))
    assert resp["statusCode"] == 403
    table.delete_item.assert_not_called()


def test_delete_customer_admin_ok(monkeypatch):
    from api_handler.routes.customers import delete_customer
    monkeypatch.setenv("ADMIN_EMAILS", "boss@mz.co.kr")
    table = MagicMock()
    monkeypatch.setattr("api_handler.routes.customers.customers_table", lambda: table)
    resp = delete_customer(_event("DELETE", "/customers/c1", email="boss@mz.co.kr",
                                  path_params={"id": "c1"}))
    assert resp["statusCode"] == 204
    table.delete_item.assert_called_once()
