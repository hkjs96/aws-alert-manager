"""
1.2.2 — 계정 등록 시 알림 이벤트 버스 PutEvents 권한 자동 부여/회수.

교차계정 PutEvents는 발신 룰의 역할(온보딩 템플릿)과 수신 버스의 정책 둘 다 필요하다.
버스 정책 쪽을 등록/삭제에 묶어 자동화한다. 우리 계정 자신은 기본 버스 룰로 들어오므로 제외.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from test_api_handler import _event

BUS = "aws-monitoring-alert-test"
CENTRAL = "949501913924"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ALERT_EVENT_BUS_NAME", BUS)
    from api_handler.routes import accounts
    accounts._events_client.cache_clear()
    accounts._current_account_id.cache_clear()
    yield
    accounts._events_client.cache_clear()
    accounts._current_account_id.cache_clear()


def _create(body, events, *, current=CENTRAL, existing=None, put_raises=False):
    from api_handler.lambda_handler import lambda_handler
    from api_handler.routes import accounts
    table = MagicMock()
    table.get_item.return_value = {"Item": existing} if existing else {}
    if put_raises:
        table.put_item.side_effect = ClientError({"Error": {"Code": "X", "Message": "x"}}, "PutItem")
    with patch.object(accounts, "accounts_table", return_value=table), \
         patch.object(accounts, "_events_client", return_value=events), \
         patch.object(accounts, "_current_account_id", return_value=current):
        resp = lambda_handler(_event("POST", "/accounts", body=body), None)
    return resp, table


def _body(account_id="222233334444"):
    return {"account_id": account_id, "role_arn": f"arn:aws:iam::{account_id}:role/R",
            "name": "prod", "customer_id": "cust-1", "regions": ["ap-northeast-2"]}


class TestGrantOnCreate:
    def test_customer_account_gets_putevents_permission(self):
        events = MagicMock()
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201, resp["body"]
        events.put_permission.assert_called_once()
        kw = events.put_permission.call_args.kwargs
        assert kw["EventBusName"] == BUS and kw["Principal"] == "222233334444"
        assert kw["Action"] == "events:PutEvents" and kw["StatementId"] == "acct-222233334444"
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "granted"
        assert json.loads(resp["body"])["alert_forwarding"] == "granted"

    def test_our_own_account_is_not_granted(self):
        events = MagicMock()
        resp, table = _create(_body(CENTRAL), events, current=CENTRAL)
        assert resp["statusCode"] == 201
        events.put_permission.assert_not_called()
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "self"

    def test_grant_failure_is_surfaced_not_fatal(self):
        events = MagicMock()
        events.put_permission.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "PutPermission")
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "grant_failed"

    def test_no_bus_env_skips_grant(self, monkeypatch):
        monkeypatch.delenv("ALERT_EVENT_BUS_NAME", raising=False)
        events = MagicMock()
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201
        events.put_permission.assert_not_called()
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "skipped"

    def test_grant_happens_before_db_write_is_persisted(self):
        """권한 결과가 DB 항목에 함께 저장돼야 이후 조회로 온보딩 상태를 알 수 있다."""
        events = MagicMock()
        _, table = _create(_body(), events, put_raises=True)
        # put 실패해도 grant는 시도됐다(등록 재시도 시 중복 grant는 멱등)
        events.put_permission.assert_called_once()


class TestRevokeOnDelete:
    def _delete(self, events, remaining, *, current=CENTRAL):
        from api_handler.lambda_handler import lambda_handler
        from api_handler.routes import accounts
        table = MagicMock()
        with patch.object(accounts, "accounts_table", return_value=table), \
             patch.object(accounts, "scan_all", return_value=remaining), \
             patch.object(accounts, "_events_client", return_value=events), \
             patch.object(accounts, "_current_account_id", return_value=current):
            resp = lambda_handler(
                _event("DELETE", "/accounts/222233334444", qs={"customer_id": "cust-1"},
                       path_params={"id": "222233334444"}), None)
        return resp

    def test_last_reference_revokes_permission(self):
        events = MagicMock()
        resp = self._delete(events, remaining=[])
        assert resp["statusCode"] == 204
        events.remove_permission.assert_called_once_with(
            EventBusName=BUS, StatementId="acct-222233334444")

    def test_account_still_used_by_another_customer_is_kept(self):
        events = MagicMock()
        resp = self._delete(events, remaining=[
            {"account_id": "222233334444", "customer_id": "cust-2"}])
        assert resp["statusCode"] == 204
        events.remove_permission.assert_not_called()

    def test_missing_permission_is_ignored(self):
        events = MagicMock()
        events.remove_permission.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "x"}}, "RemovePermission")
        resp = self._delete(events, remaining=[])
        assert resp["statusCode"] == 204

    def test_our_own_account_is_not_revoked(self):
        events = MagicMock()
        from api_handler.lambda_handler import lambda_handler
        from api_handler.routes import accounts
        table = MagicMock()
        with patch.object(accounts, "accounts_table", return_value=table), \
             patch.object(accounts, "scan_all", return_value=[]), \
             patch.object(accounts, "_events_client", return_value=events), \
             patch.object(accounts, "_current_account_id", return_value=CENTRAL):
            resp = lambda_handler(
                _event("DELETE", f"/accounts/{CENTRAL}", qs={"customer_id": "cust-1"},
                       path_params={"id": CENTRAL}), None)
        assert resp["statusCode"] == 204
        events.remove_permission.assert_not_called()
