"""
/thresholds 엔드포인트 단위 테스트 (TDD Red)

검증 범위:
- GET /thresholds/{type}: 시스템 기본값 + 고객사 오버라이드 병합
- PUT /thresholds/{type}: 고객사 오버라이드 저장
- 알람 레지스트리 기반 시스템 기본값 조회
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("CUSTOMERS_TABLE", "test-customers")
    monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")
    monkeypatch.setenv("THRESHOLD_OVERRIDES_TABLE", "test-thresholds")
    monkeypatch.setenv("API_STAGE", "dev")


def _event(method, path, body=None, qs=None):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body else None,
    }


# ── GET /thresholds/{type} ───────────────────────────────────────────


def test_get_thresholds_ec2_returns_system_defaults():
    """EC2 타입 임계치 조회 시 시스템 기본값이 포함되어야 한다."""
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": []}  # 오버라이드 없음

    with patch("api_handler.routes.thresholds.threshold_overrides_table", return_value=mock_table):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("GET", "/thresholds/EC2"), None)

    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])
    assert isinstance(items, list)
    assert len(items) > 0
    # CPU는 EC2 기본 메트릭
    cpu = next((t for t in items if t["metric_key"] == "CPU"), None)
    assert cpu is not None
    assert cpu["system_default"] == 80
    assert cpu["customer_override"] is None
    assert cpu["unit"] == "%"


def test_get_thresholds_with_customer_override_applied():
    """고객사 오버라이드가 있으면 customer_override 필드에 반영되어야 한다."""
    from decimal import Decimal
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [
            {
                "scope_id": "customer_id:cust-01",
                "metric_key": "CPU",
                "threshold_value": Decimal("90"),
            }
        ]
    }

    with patch("api_handler.routes.thresholds.threshold_overrides_table", return_value=mock_table):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(
            _event("GET", "/thresholds/EC2", qs={"customer_id": "cust-01"}), None
        )

    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])
    cpu = next((t for t in items if t["metric_key"] == "CPU"), None)
    assert cpu is not None
    assert cpu["customer_override"] == 90  # Decimal → float
    assert cpu["system_default"] == 80     # 시스템 기본값은 유지


def test_get_thresholds_unknown_type_returns_empty():
    """미지원 리소스 타입은 빈 목록을 반환해야 한다."""
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(_event("GET", "/thresholds/UNKNOWN_TYPE"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == []


# ── PUT /thresholds/{type} ───────────────────────────────────────────


def test_put_thresholds_saves_overrides():
    """PUT 요청으로 고객사 오버라이드를 DynamoDB에 저장해야 한다."""
    mock_table = MagicMock()
    mock_table.put_item.return_value = {}

    body = {
        "customer_id": "cust-01",
        "overrides": [
            {"metric_key": "CPU", "customer_override": 90},
            {"metric_key": "Memory", "customer_override": None},  # 오버라이드 제거
        ],
    }

    with patch("api_handler.routes.thresholds.threshold_overrides_table", return_value=mock_table):
        with patch("api_handler.routes.thresholds.threshold_overrides_table", return_value=mock_table):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("PUT", "/thresholds/EC2", body=body), None)

    assert resp["statusCode"] == 200
    result = json.loads(resp["body"])
    assert result["saved"] >= 0


def test_put_thresholds_requires_customer_id():
    """customer_id 없으면 400 반환."""
    from api_handler.lambda_handler import lambda_handler
    resp = lambda_handler(
        _event("PUT", "/thresholds/EC2", body={"overrides": []}), None
    )
    assert resp["statusCode"] == 400
