"""
리소스 URL 식별자 토큰 디코딩 테스트 — api_handler.routes.resources

`_decode_resource_token`은 프론트엔드 `encodeResourceId`가 만든 base64url 토큰
(`r.<payload>`)을 원본 resource_id로 복원한다. ARN처럼 슬래시·콜론을 포함한
resource_id가 URL/API path를 통과하도록 보장하는 핵심 로직이다(루트 AGENTS.md AP-6).
"""

import base64
import json

from unittest.mock import patch

import pytest

from api_handler.routes.resources import _decode_resource_token


@pytest.fixture(autouse=True)
def _inventory_env(monkeypatch):
    # test_api_routes.py와 동일하게 가짜 자격증명을 설정한다. 이 모듈이 boto3
    # 기본 세션을 먼저 생성하더라도(예: resource_inventory_table → boto3.resource)
    # 전역 세션이 자격증명 없이 캐시돼 다른 모듈의 실호출 테스트를 오염시키지 않도록.
    monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


TG_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:949501913924:"
    "targetgroup/dev-e2e-alb-tg-ip/ef28a16dfd6f7523"
)


def _token(resource_id: str) -> str:
    """프론트엔드 encodeResourceId와 동일하게 base64url 토큰을 만든다."""
    payload = base64.urlsafe_b64encode(resource_id.encode("utf-8")).decode("ascii").rstrip("=")
    return "r." + payload


def _event(method: str, path: str) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": {},
        "pathParameters": {},
        "body": None,
    }


def _resource_snapshot(resource_id: str, resource_type: str) -> dict:
    return {
        "resource_id": resource_id,
        "entity_type": "resource",
        "name": resource_id,
        "type": resource_type,
        "status": "active",
        "monitoring": True,
        "alarm_count": 0,
        "critical_count": 0,
        "warning_count": 0,
    }


class TestDecodeResourceToken:

    def test_round_trips_arn_token(self):
        assert _decode_resource_token(_token(TG_ARN)) == TG_ARN

    def test_round_trips_instance_id_token(self):
        assert _decode_resource_token(_token("i-04fdf4b064295b776")) == "i-04fdf4b064295b776"

    def test_raw_instance_id_passes_through(self):
        # 레거시 raw URL(접두사 없음)은 그대로 통과한다.
        assert _decode_resource_token("i-04fdf4b064295b776") == "i-04fdf4b064295b776"

    def test_raw_name_passes_through(self):
        assert _decode_resource_token("my-resource-name") == "my-resource-name"

    def test_token_has_no_slash_or_colon(self):
        token = _token(TG_ARN)
        assert "/" not in token and ":" not in token

    def test_malformed_token_falls_back_to_raw(self):
        # 접두사는 있지만 payload가 유효한 base64url이 아니면 raw로 보존한다.
        assert _decode_resource_token("r.not valid!!") == "r.not valid!!"

    def test_prefix_collision_with_non_token_preserved(self):
        # `.`은 base64url 알파벳이 아니므로 디코딩 실패 → 원본 보존(S3 버킷 등).
        assert _decode_resource_token("r.example.com") == "r.example.com"


class TestTokenRouting:

    def test_arn_resource_resolves_via_token(self):
        """슬래시 포함 ARN도 토큰 경로로 상세 조회가 200을 반환한다."""
        db_items = [_resource_snapshot(TG_ARN, "TG")]
        path = f"/resources/{_token(TG_ARN)}"
        # 토큰 경로에는 슬래시가 없어 라우터 `[^/]+`가 단일 세그먼트로 매칭한다.
        assert path.count("/") == 2  # "/resources/" 뒤로 추가 슬래시 없음

        with patch("api_handler.routes.resources.scan_all", return_value=db_items):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", path), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == TG_ARN
        assert body["type"] == "TG"
