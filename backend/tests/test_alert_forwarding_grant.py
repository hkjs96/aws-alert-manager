"""
1.2.2 — 계정 등록 시 알림 이벤트 버스 PutEvents 권한 자동 부여/회수.

교차계정 PutEvents는 발신 룰의 역할(온보딩 템플릿)과 수신 버스의 정책 둘 다 필요하다.
버스 정책 쪽을 등록/삭제에 묶어 자동화한다. 우리 계정 자신은 기본 버스 룰로 들어오므로 제외.

**PutPermission(Policy=...)는 정책 전체를 교체한다**(실측). 그래서 읽고-합쳐-쓰기이며, 여기서
고정하는 핵심은 "고객사를 추가해도 기존 고객사 권한이 남는가"다 — 깨지면 그 계정 알람이
조용히 끊긴다. 조건(source·detail-type)도 함께 고정한다.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from test_api_handler import _event

BUS = "aws-monitoring-alert-test"
BUS_ARN = f"arn:aws:events:us-east-1:949501913924:event-bus/{BUS}"
CENTRAL = "949501913924"


def fake_events(existing=None):
    """describe/put/remove가 맞물리는 가짜 EventBridge — **전체 교체** 의미론까지 재현한다."""
    state = {"statements": list(existing or [])}
    client = MagicMock()

    def _describe(Name, **_):
        out = {"Arn": BUS_ARN}
        if state["statements"]:
            out["Policy"] = json.dumps(
                {"Version": "2012-10-17", "Statement": state["statements"]})
        return out

    def _put(EventBusName, Policy=None, **_):
        state["statements"] = list(json.loads(Policy)["Statement"])

    def _remove(EventBusName, RemoveAllPermissions=None, StatementId=None, **_):
        if RemoveAllPermissions:
            state["statements"] = []
        else:
            state["statements"] = [x for x in state["statements"]
                                   if x.get("Sid") != StatementId]

    client.describe_event_bus.side_effect = _describe
    client.put_permission.side_effect = _put
    client.remove_permission.side_effect = _remove
    client.statements = state
    return client


def other_statement(sid="acct-999988887777"):
    return {"Sid": sid, "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::999988887777:root"},
            "Action": "events:PutEvents", "Resource": BUS_ARN}


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
        events = fake_events()
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201, resp["body"]
        stmt = events.statements["statements"][0]
        assert stmt["Sid"] == "acct-222233334444"
        assert stmt["Action"] == "events:PutEvents"
        assert stmt["Principal"] == {"AWS": "arn:aws:iam::222233334444:root"}
        assert stmt["Resource"] == BUS_ARN
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "granted"
        assert json.loads(resp["body"])["alert_forwarding"] == "granted"

    def test_grant_is_limited_to_alarm_events(self):
        """조건이 없으면 등록된 계정이 아무 이벤트나 우리 버스에 넣을 수 있다."""
        events = fake_events()
        _create(_body(), events)
        cond = events.statements["statements"][0]["Condition"]["ForAllValues:StringEquals"]
        assert cond["events:source"] == "aws.cloudwatch"
        assert cond["events:detail-type"] == [
            "CloudWatch Alarm State Change", "CloudWatch Alarm Configuration Change"]

    def test_existing_customers_keep_their_permission(self):
        """전체 교체 API다 — 합치지 않으면 앞 고객사의 알람이 그날부터 조용히 끊긴다."""
        events = fake_events([other_statement()])
        resp, _ = _create(_body(), events)
        assert resp["statusCode"] == 201
        assert {x["Sid"] for x in events.statements["statements"]} == {
            "acct-999988887777", "acct-222233334444"}

    def test_re_registering_does_not_duplicate(self):
        events = fake_events()
        _create(_body(), events)
        _create(_body(), events)
        assert [x["Sid"] for x in events.statements["statements"]] == ["acct-222233334444"]

    def test_lost_statement_is_reported_not_silently_accepted(self):
        """동시 등록이 서로를 지울 수 있다 — 확인해서 grant_failed로 드러낸다."""
        events = fake_events([other_statement()])

        def _drops_others(EventBusName, Policy=None, **_):
            events.statements["statements"] = [
                x for x in json.loads(Policy)["Statement"] if x["Sid"] == "acct-222233334444"]
        events.put_permission.side_effect = _drops_others
        _, table = _create(_body(), events)
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "grant_failed"

    def test_unparseable_policy_is_not_overwritten(self):
        events = MagicMock()
        events.describe_event_bus.return_value = {"Arn": BUS_ARN, "Policy": "{not json"}
        _, table = _create(_body(), events)
        events.put_permission.assert_not_called()
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "grant_failed"

    def test_our_own_account_is_not_granted(self):
        events = fake_events()
        resp, table = _create(_body(CENTRAL), events, current=CENTRAL)
        assert resp["statusCode"] == 201
        events.put_permission.assert_not_called()
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "self"

    def test_grant_failure_is_surfaced_not_fatal(self):
        events = fake_events()
        events.put_permission.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "PutPermission")
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "grant_failed"

    def test_no_bus_env_skips_grant(self, monkeypatch):
        monkeypatch.delenv("ALERT_EVENT_BUS_NAME", raising=False)
        events = fake_events()
        resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201
        events.put_permission.assert_not_called()
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "skipped"

    def test_grant_happens_before_db_write_is_persisted(self):
        """권한 결과가 DB 항목에 함께 저장돼야 이후 조회로 온보딩 상태를 알 수 있다."""
        events = fake_events()
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
        events = fake_events([other_statement("acct-222233334444"), other_statement()])
        resp = self._delete(events, remaining=[])
        assert resp["statusCode"] == 204
        assert {x["Sid"] for x in events.statements["statements"]} == {"acct-999988887777"}, \
            "다른 고객사 권한까지 지우면 안 된다"

    def test_revoking_the_only_statement_clears_the_policy(self):
        events = fake_events([other_statement("acct-222233334444")])
        self._delete(events, remaining=[])
        assert events.statements["statements"] == []

    def test_account_still_used_by_another_customer_is_kept(self):
        events = fake_events([other_statement("acct-222233334444")])
        resp = self._delete(events, remaining=[
            {"account_id": "222233334444", "customer_id": "cust-2"}])
        assert resp["statusCode"] == 204
        assert {x["Sid"] for x in events.statements["statements"]} == {"acct-222233334444"}

    def test_missing_permission_is_ignored(self):
        events = fake_events()
        resp = self._delete(events, remaining=[])
        assert resp["statusCode"] == 204

    def test_our_own_account_is_not_revoked(self):
        events = fake_events()
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
        events.put_permission.assert_not_called()
