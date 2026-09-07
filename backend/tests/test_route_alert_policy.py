"""
/alert/policy · /alert/silences 라우트 테스트 — tasks 1.4.4 / 1.4.6

정제 설정은 잘못 만지면 알림이 통째로 사라진다. 그래서 권한을 폭발 반경으로 나눴고,
그 경계를 여기서 고정한다:
- 정책 변경(전역) → 관리자만
- 고객사 지정 정비창 → 누구나 / **고객사 미지정(전역) 정비창 → 관리자만**
- 저장소 오류는 503으로 드러난다 (조용히 200을 주지 않는다)
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from fakes_ddb import FakeConfigTable
from api_handler.routes import alert_policy as ap
from common.alert_config import CONFIG_POLICY, CONFIG_SILENCE, POLICY_DEFAULT

ADMIN, USER = "admin@mz.co.kr", "user@mz.co.kr"


@pytest.fixture
def table():
    t = FakeConfigTable()
    with patch.object(ap, "alert_policy_table", return_value=t):
        yield t


@pytest.fixture
def admin_mode(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)


def event(method="GET", *, body=None, email="", path_params=None, qs=None):
    e: dict = {"requestContext": {"http": {"method": method}}}
    if email:
        e["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": email}}}
    if body is not None:
        e["body"] = json.dumps(body)
    if path_params:
        e["pathParameters"] = path_params
    if qs:
        e["queryStringParameters"] = qs
    return e


def body_of(resp):
    return json.loads(resp["body"])


def broken(op="GetItem"):
    class Broken:
        def __getattr__(self, _):
            def fail(**__):
                raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, op)
            return fail
    return Broken()


class TestGetPolicy:
    def test_env_source_when_db_empty(self, table):
        resp = ap.get_policy(event())
        assert resp["statusCode"] == 200
        data = body_of(resp)
        assert data["source"] == "env"
        assert data["policy"]["repeat_interval_sec"] == 900          # U6 기본값
        assert "flapping_per_day" in data["policy"]

    def test_db_source_and_merge(self, table):
        table.put_item(Item={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT,
                             "repeat_interval_sec": 1800, "updated_by": ADMIN,
                             "updated_at": "2026-09-08T00:00:00Z"})
        data = body_of(ap.get_policy(event()))
        assert data["source"] == "db"
        assert data["policy"]["repeat_interval_sec"] == 1800
        assert data["updated_by"] == ADMIN

    def test_storage_error_is_503(self):
        with patch.object(ap, "alert_policy_table", return_value=broken()):
            assert ap.get_policy(event())["statusCode"] == 503


class TestPutPolicy:
    def test_saves_and_returns_effective(self, table):
        resp = ap.put_policy(event("PUT", body={"repeat_interval_sec": 1200,
                                                "auto_pause_sec": {"SEV-3": 300}}, email=USER))
        assert resp["statusCode"] == 200
        assert body_of(resp)["policy"]["repeat_interval_sec"] == 1200
        saved = table.items[(CONFIG_POLICY, POLICY_DEFAULT)]
        assert saved["auto_pause_sec"] == {"SEV-3": 300} and saved["updated_by"] == USER

    def test_admin_only_when_enforced(self, table, admin_mode):
        denied = ap.put_policy(event("PUT", body={"repeat_interval_sec": 1200}, email=USER))
        assert denied["statusCode"] == 403 and not table.items
        allowed = ap.put_policy(event("PUT", body={"repeat_interval_sec": 1200}, email=ADMIN))
        assert allowed["statusCode"] == 200

    def test_validation_error_is_400(self, table):
        resp = ap.put_policy(event("PUT", body={"repeat_interval_sec": 10 ** 9}, email=ADMIN))
        assert resp["statusCode"] == 400 and body_of(resp)["code"] == "VALIDATION_ERROR"
        assert not table.items

    def test_malformed_json_is_400(self, table):
        e = event("PUT", email=ADMIN)
        e["body"] = "{nope"
        assert ap.put_policy(e)["statusCode"] == 400

    def test_storage_error_is_503(self, admin_mode):
        with patch.object(ap, "alert_policy_table", return_value=broken("PutItem")):
            resp = ap.put_policy(event("PUT", body={"repeat_interval_sec": 1200}, email=ADMIN))
        assert resp["statusCode"] == 503


class TestSilences:
    def _create(self, hours=2, **over):
        end = datetime.now(timezone.utc) + timedelta(hours=hours)
        return {"ends_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "customer_id": "cust-1", **over}

    def test_create_and_list(self, table):
        resp = ap.create_silence(event("POST", body=self._create(reason="DB 패치"), email=USER))
        assert resp["statusCode"] == 201
        created = body_of(resp)
        assert created["active"] is True and created["reason"] == "DB 패치"
        assert created["created_by"] == USER

        listed = body_of(ap.list_silences(event()))
        assert listed["active"] == 1 and len(listed["silences"]) == 1
        assert listed["silences"][0]["id"] == created["id"]

    def test_global_silence_requires_admin(self, table, admin_mode):
        body = self._create(customer_id="")
        denied = ap.create_silence(event("POST", body=body, email=USER))
        assert denied["statusCode"] == 403 and not table.items

        scoped = ap.create_silence(event("POST", body=self._create(), email=USER))
        assert scoped["statusCode"] == 201          # 고객사 지정은 일반 사용자도 가능

        allowed = ap.create_silence(event("POST", body=body, email=ADMIN))
        assert allowed["statusCode"] == 201

    def test_validation_error_is_400(self, table):
        assert ap.create_silence(event("POST", body={}, email=USER))["statusCode"] == 400
        past = {"ends_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        assert ap.create_silence(event("POST", body=past, email=USER))["statusCode"] == 400
        assert not table.items

    def test_expired_hidden_unless_requested(self, table):
        past_start = datetime.now(timezone.utc) - timedelta(hours=3)
        table.put_item(Item={"config_type": CONFIG_SILENCE, "config_id": "old",
                             "starts_at": past_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "ends_at": (past_start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "customer_id": "cust-1"})
        assert body_of(ap.list_silences(event()))["silences"] == []
        with_expired = body_of(ap.list_silences(event(qs={"include_expired": "true"})))
        assert len(with_expired["silences"]) == 1 and with_expired["silences"][0]["expired"] is True

    def test_list_paginates(self, table):
        for i in range(5):
            ap.create_silence(event("POST", body=self._create(reason=f"r{i}"), email=USER))
        table.page_size = 2
        assert len(body_of(ap.list_silences(event()))["silences"]) == 5

    def test_delete(self, table):
        created = body_of(ap.create_silence(event("POST", body=self._create(), email=USER)))
        resp = ap.delete_silence(event("DELETE", email=USER, path_params={"id": created["id"]}))
        assert resp["statusCode"] == 200 and body_of(resp)["was_active"] is True
        assert not table.items

    def test_delete_missing_is_404(self, table):
        assert ap.delete_silence(
            event("DELETE", email=USER, path_params={"id": "nope"}))["statusCode"] == 404

    def test_delete_global_requires_admin(self, table, admin_mode):
        created = body_of(ap.create_silence(
            event("POST", body=self._create(customer_id=""), email=ADMIN)))
        denied = ap.delete_silence(event("DELETE", email=USER, path_params={"id": created["id"]}))
        assert denied["statusCode"] == 403 and table.items
        assert ap.delete_silence(
            event("DELETE", email=ADMIN, path_params={"id": created["id"]}))["statusCode"] == 200

    def test_missing_id_is_400(self, table):
        assert ap.delete_silence(event("DELETE", email=USER))["statusCode"] == 400

    def test_storage_error_is_503(self):
        with patch.object(ap, "alert_policy_table", return_value=broken("Query")):
            assert ap.list_silences(event())["statusCode"] == 503


class TestRouting:
    """라우트가 실제로 등록돼 있는가 — 모듈만 만들고 붙이지 않는 실수를 막는다."""

    def test_routes_registered(self):
        from api_handler import lambda_handler as lh
        registered = {(m, p.pattern) for m, p, _ in lh._ROUTES}
        assert ("GET", r"^/alert/policy$") in registered
        assert ("PUT", r"^/alert/policy$") in registered
        assert ("GET", r"^/alert/silences$") in registered
        assert ("POST", r"^/alert/silences$") in registered
        assert ("DELETE", r"^/alert/silences/(?P<id>[^/]+)$") in registered
