"""
api_handler 라우터 + 주요 엔드포인트 단위 테스트

검증 범위:
- 라우터: 경로/메서드 매칭, 404, CORS 헤더
- /health: 정상 응답
- /customers: GET/POST/DELETE 기본 흐름
- /accounts: GET/POST/test 기본 흐름
- /dashboard/stats: CloudWatch 집계
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ── 픽스처 ──────────────────────────────────────────────────────────

def _event(method: str, path: str, body=None, qs=None, path_params=None) -> dict:
    """API Gateway HTTP API v2 이벤트 생성 헬퍼."""
    event = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": qs or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
    }
    return event


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("CUSTOMERS_TABLE", "test-customers")
    monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")
    monkeypatch.setenv("THRESHOLD_OVERRIDES_TABLE", "test-thresholds")
    monkeypatch.setenv("API_STAGE", "dev")


# ── 라우터 ──────────────────────────────────────────────────────────


def test_health_returns_200():
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("GET", "/health"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"


def test_cors_headers_always_present():
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("GET", "/health"), None)
    assert "Access-Control-Allow-Origin" in resp["headers"]
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


def test_unknown_route_returns_404():
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("GET", "/nonexistent"), None)
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert body["code"] == "NOT_FOUND"


def test_stage_prefix_stripped():
    """API Gateway stage prefix가 라우팅에서 제거되어야 한다."""
    from api_handler.lambda_handler import lambda_handler
    event = _event("GET", "/dev/health")
    event["rawPath"] = "/dev/health"
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200


# ── /customers ───────────────────────────────────────────────────────


def test_list_customers_returns_items():
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        "Items": [{"customer_id": "cust-01", "name": "테스트고객"}]
    }
    mock_accounts_table = MagicMock()
    mock_accounts_table.scan.return_value = {"Items": []}

    with patch("api_handler.routes.customers.customers_table", return_value=mock_table):
        with patch("api_handler.routes.customers.accounts_table", return_value=mock_accounts_table):
            with patch("api_handler.db.scan_all") as mock_scan:
                mock_scan.side_effect = [
                    [{"customer_id": "cust-01", "name": "테스트고객"}],
                    [],  # accounts
                ]
                from api_handler.lambda_handler import lambda_handler
                resp = lambda_handler(_event("GET", "/customers"), None)

    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])
    assert isinstance(items, list)


def test_create_customer_validates_required_fields():
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("POST", "/customers", body={"name": "테스트"}), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["code"] == "VALIDATION_ERROR"


def test_create_customer_success():
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}  # 중복 없음
    mock_table.put_item.return_value = {}

    with patch("api_handler.routes.customers.customers_table", return_value=mock_table):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(
            _event("POST", "/customers", body={"name": "신규고객", "code": "new-01"}), None
        )

    assert resp["statusCode"] == 201
    item = json.loads(resp["body"])
    assert item["customer_id"] == "new-01"
    assert item["name"] == "신규고객"


def test_create_customer_rejects_duplicate():
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": {"customer_id": "dup"}}

    with patch("api_handler.routes.customers.customers_table", return_value=mock_table):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(
            _event("POST", "/customers", body={"name": "중복", "code": "dup"}), None
        )

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["code"] == "DUPLICATE"


def test_delete_customer_returns_204():
    mock_table = MagicMock()
    mock_table.delete_item.return_value = {}

    with patch("api_handler.routes.customers.customers_table", return_value=mock_table):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("DELETE", "/customers/cust-01"), None)

    assert resp["statusCode"] == 204


# ── /accounts ────────────────────────────────────────────────────────


def test_list_accounts_filtered_by_customer():
    """customer_id 쿼리파라미터로 필터링된 결과가 반환되어야 한다."""
    mock_table = MagicMock()

    with patch("api_handler.routes.accounts.accounts_table", return_value=mock_table):
        with patch("api_handler.routes.accounts.query_by_pk", return_value=[
            {"customer_id": "cust-01", "account_id": "111111111111", "name": "계정1"}
        ]):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/accounts", qs={"customer_id": "cust-01"}), None
            )

    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])
    assert len(items) == 1
    assert items[0]["account_id"] == "111111111111"


def test_create_account_validates_required_fields():
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("POST", "/accounts", body={"name": "미완성"}), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["code"] == "VALIDATION_ERROR"


# ── /dashboard/stats ─────────────────────────────────────────────────


def test_dashboard_stats_returns_expected_shape():
    mock_alarms = [
        {"AlarmName": "[EC2] server CPU >80% (TagName: i-001)", "StateValue": "OK", "Tags": []},
        {"AlarmName": "[EC2] server CPU >80% (TagName: i-001)", "StateValue": "ALARM", "Tags": []},
        {"AlarmName": "[RDS] db free <2GB (TagName: db-001)", "StateValue": "OK", "Tags": []},
    ]
    with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("GET", "/dashboard/stats"), None)

    assert resp["statusCode"] == 200
    stats = json.loads(resp["body"])
    assert "monitored_count" in stats
    assert "active_alarms" in stats
    assert stats["active_alarms"] == 1  # ALARM 상태 1개
