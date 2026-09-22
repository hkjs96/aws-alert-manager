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


def _reconcile(events, rows, *, current=CENTRAL):
    from api_handler.routes import accounts
    with patch.object(accounts, "accounts_table", return_value=MagicMock()), \
         patch.object(accounts, "scan_all", return_value=rows), \
         patch.object(accounts, "_events_client", return_value=events), \
         patch.object(accounts, "_current_account_id", return_value=current):
        return accounts.reconcile_alert_forwarding()


class TestReconcile:
    """주기 점검이 계정 표와 버스 정책을 수렴시킨다 (review-phase2 L1).

    등록 경로의 read-back은 A읽→B읽→A씀✓→B씀✓ 인터리빙을 못 잡는다 — A의 권한이 사라지는데 둘 다
    granted다. 그 손실은 "그 계정 알람이 안 온다"로만 드러나므로 한 시간 안에 되돌아와야 한다.
    """

    def test_missing_statement_is_re_added_with_conditions(self):
        events = fake_events()
        out = _reconcile(events, [{"account_id": "111122223333"}])
        assert out["added"] == ["acct-111122223333"] and out["changed"] is True
        stmt = next(s for s in events.statements["statements"] if s["Sid"] == "acct-111122223333")
        assert stmt["Condition"]["ForAllValues:StringEquals"]["events:source"] == "aws.cloudwatch"

    def test_stale_account_statement_is_removed_but_foreign_ones_are_kept(self):
        foreign = {"Sid": "manual-ops", "Effect": "Allow",
                   "Principal": {"AWS": "arn:aws:iam::555555555555:root"},
                   "Action": "events:PutEvents", "Resource": BUS_ARN}
        events = fake_events(existing=[other_statement("acct-999988887777"), foreign])
        out = _reconcile(events, [])
        assert out["removed"] == ["acct-999988887777"]
        assert [s["Sid"] for s in events.statements["statements"]] == ["manual-ops"], \
            "우리가 만들지 않은 statement는 건드리지 않는다"

    def test_outdated_statement_without_conditions_is_refreshed(self):
        events = fake_events(existing=[other_statement("acct-999988887777")])      # P2 이전 형식
        out = _reconcile(events, [{"account_id": "999988887777"}])
        assert out["updated"] == ["acct-999988887777"] and out["added"] == []
        assert "Condition" in events.statements["statements"][0]

    def test_no_drift_means_no_write(self):
        from api_handler.routes import accounts
        events = fake_events(existing=[accounts._forward_statement("111122223333", BUS_ARN)])
        out = _reconcile(events, [{"account_id": "111122223333"}])
        assert out["changed"] is False
        events.put_permission.assert_not_called()
        events.remove_permission.assert_not_called()

    def test_our_own_account_is_never_added(self):
        events = fake_events()
        out = _reconcile(events, [{"account_id": CENTRAL}])
        assert out["changed"] is False and events.statements["statements"] == []

    def test_unparseable_policy_is_left_alone(self):
        events = fake_events()
        events.describe_event_bus.side_effect = lambda **_: {"Arn": BUS_ARN, "Policy": "{not json"}
        out = _reconcile(events, [{"account_id": "111122223333"}])
        assert "error" in out
        events.put_permission.assert_not_called()

    def test_scheduled_invocation_reaches_the_reconciler(self):
        from api_handler.lambda_handler import lambda_handler
        from api_handler.routes import accounts
        events = fake_events()
        with patch.object(accounts, "accounts_table", return_value=MagicMock()), \
             patch.object(accounts, "scan_all", return_value=[{"account_id": "111122223333"}]), \
             patch.object(accounts, "_events_client", return_value=events), \
             patch.object(accounts, "_current_account_id", return_value=CENTRAL):
            out = lambda_handler({"action": "reconcile-alert-forwarding"}, None)
        assert out["added"] == ["acct-111122223333"]

    def test_manual_route_is_admin_only(self, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "admin@mz.co.kr")
        from api_handler.lambda_handler import lambda_handler
        from api_handler.routes import accounts
        ev = _event("POST", "/accounts/alert-forwarding/reconcile")
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": "member@mz.co.kr"}}}
        events = fake_events()
        with patch.object(accounts, "accounts_table", return_value=MagicMock()), \
             patch.object(accounts, "scan_all", return_value=[]), \
             patch.object(accounts, "_events_client", return_value=events), \
             patch.object(accounts, "_current_account_id", return_value=CENTRAL):
            denied = lambda_handler(ev, None)
            ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": "admin@mz.co.kr"}}}
            allowed = lambda_handler(ev, None)
        assert denied["statusCode"] == 403
        assert allowed["statusCode"] == 200 and json.loads(allowed["body"])["changed"] is False


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


# ──────────────────────────────────────────────
# 2026-09-22 — 전달이 끊기면 드러나게 한다.
# AssumeRole이 되는 것과 알람 이벤트가 도착하는 것은 다른 조건이다. 그전까지 연결 테스트는 앞만 봐서
# "연결됨"인데 알람은 영영 오지 않는 상태(등록 전 온보딩 스택, 동시 등록으로 지워진 statement)를
# 통과시켰고, 주기 점검은 손실을 조용히 되돌렸다.
# ──────────────────────────────────────────────


def _test_conn(account_id="222233334444", events=None, *, current=CENTRAL,
               region_status="connected", assume_raises=False):
    from api_handler.lambda_handler import lambda_handler
    from api_handler.routes import accounts
    table = MagicMock()
    table.get_item.return_value = {"Item": {
        "customer_id": "cust-1", "account_id": account_id,
        "role_arn": f"arn:aws:iam::{account_id}:role/R", "regions": ["ap-northeast-2"]}}
    assume = patch.object(accounts, "_assume_role_kwargs", return_value={})
    if assume_raises:
        assume = patch.object(accounts, "_assume_role_kwargs", side_effect=ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole"))
    with patch.object(accounts, "accounts_table", return_value=table), \
         patch.object(accounts, "_events_client", return_value=events if events is not None else fake_events()), \
         patch.object(accounts, "_current_account_id", return_value=current), \
         assume, \
         patch.object(accounts, "_test_region_access",
                      return_value={"region": "ap-northeast-2", "status": region_status}):
        resp = lambda_handler(
            _event("POST", f"/accounts/{account_id}/test", qs={"customer_id": "cust-1"},
                   path_params={"id": account_id}), None)
    return resp, table


def _granted_events(account_id="222233334444"):
    """이미 정상적으로 부여된 상태의 버스."""
    events = fake_events()
    _create(_body(account_id), events)
    return events


class TestConnectionTestSeesForwarding:
    def test_present_statement_is_reported_ok(self):
        resp, _ = _test_conn(events=_granted_events())
        body = json.loads(resp["body"])
        assert resp["statusCode"] == 200
        assert body["status"] == "connected"
        assert body["alert_forwarding"]["status"] == "ok"

    def test_missing_statement_is_repaired_and_said_so(self):
        """온보딩 스택만 배포하고 등록 전이거나, 동시 등록이 지운 경우 — 그 사이 이벤트는 이미 버려졌다."""
        events = fake_events()
        resp, _ = _test_conn(events=events)
        body = json.loads(resp["body"])
        assert body["alert_forwarding"]["status"] == "repaired"
        assert "dropped" in body["alert_forwarding"]["detail"]
        assert [x["Sid"] for x in events.statements["statements"]] == ["acct-222233334444"]

    def test_outdated_statement_without_conditions_is_repaired(self):
        events = fake_events([other_statement("acct-222233334444")])   # 조건 없는 옛 형식
        resp, _ = _test_conn(events=events)
        assert json.loads(resp["body"])["alert_forwarding"]["status"] == "repaired"
        stmt = events.statements["statements"][0]
        assert stmt["Condition"]["ForAllValues:StringEquals"]["events:source"] == "aws.cloudwatch"

    def test_unrepairable_policy_is_reported_failed_and_alerted(self):
        events = fake_events()
        events.describe_event_bus.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}}, "DescribeEventBus")
        from api_handler.routes import accounts
        with patch.object(accounts, "send_error_alert") as alert:
            resp, _ = _test_conn(events=events)
        assert json.loads(resp["body"])["alert_forwarding"]["status"] == "failed"
        alert.assert_not_called()      # 읽기 실패는 호출자가 화면에서 본다 — 알림은 고치지 못했을 때만

    def test_repair_failure_raises_an_operational_alert(self):
        events = fake_events()
        events.put_permission.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}}, "PutPermission")
        from api_handler.routes import accounts
        with patch.object(accounts, "send_error_alert") as alert:
            resp, _ = _test_conn(events=events)
        assert json.loads(resp["body"])["alert_forwarding"]["status"] == "failed"
        alert.assert_called_once()

    def test_status_still_means_assume_role_and_region_access(self):
        """기존 동작 보존 — `status`의 의미를 바꾸면 화면·저장된 connection_status가 어긋난다."""
        resp, _ = _test_conn(events=fake_events())          # 전달은 repaired, 리전은 정상
        body = json.loads(resp["body"])
        assert body["status"] == "connected"
        resp, _ = _test_conn(events=_granted_events(), region_status="failed")
        body = json.loads(resp["body"])
        assert body["status"] == "failed" and body["alert_forwarding"]["status"] == "ok"

    def test_forwarding_is_checked_even_when_assume_role_fails(self):
        """둘은 독립된 조건이다 — 역할이 깨져도 전달 상태는 진단에 필요하다."""
        resp, _ = _test_conn(events=_granted_events(), assume_raises=True)
        body = json.loads(resp["body"])
        assert body["status"] == "failed"
        assert body["alert_forwarding"]["status"] == "ok"

    def test_forwarding_status_is_persisted_next_to_the_connection_status(self):
        _, table = _test_conn(events=_granted_events())
        values = table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        assert values[":f"] == "ok" and values[":s"] == "connected"
        assert "alert_forwarding" in table.update_item.call_args.kwargs["UpdateExpression"]

    def test_our_own_account_needs_no_cross_account_policy(self):
        resp, _ = _test_conn(account_id=CENTRAL, events=fake_events())
        assert json.loads(resp["body"])["alert_forwarding"]["status"] == "self"

    def test_no_bus_configured_is_skipped_not_failed(self, monkeypatch):
        monkeypatch.delenv("ALERT_EVENT_BUS_NAME", raising=False)
        resp, _ = _test_conn(events=fake_events())
        assert json.loads(resp["body"])["alert_forwarding"]["status"] == "skipped"


class TestForwardingFailuresAreReported:
    """조용한 복구는 손실이 있었다는 사실까지 지운다 — 수렴은 자동, 보고는 사람에게."""

    def test_reconcile_drift_raises_an_operational_alert(self):
        from api_handler.routes import accounts
        events = fake_events()
        with patch.object(accounts, "send_error_alert") as alert:
            out = _reconcile(events, [{"account_id": "111122223333"}])
        assert out["changed"] is True
        alert.assert_called_once()
        assert "acct-111122223333" in alert.call_args.kwargs["error"].args[0]

    def test_reconcile_without_drift_stays_quiet(self):
        from api_handler.routes import accounts
        events = _granted_events()
        with patch.object(accounts, "send_error_alert") as alert:
            out = _reconcile(events, [{"account_id": "222233334444"}])
        assert out["changed"] is False
        alert.assert_not_called()

    def test_reconcile_read_failure_raises_an_operational_alert(self):
        from api_handler.routes import accounts
        events = fake_events()
        events.describe_event_bus.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}}, "DescribeEventBus")
        with patch.object(accounts, "send_error_alert") as alert:
            out = _reconcile(events, [{"account_id": "111122223333"}])
        assert "error" in out
        alert.assert_called_once()

    def test_failed_grant_on_registration_raises_an_operational_alert(self):
        """등록은 201로 성공시킨다(기존 동작) — 대신 조용히 넘어가지 않는다."""
        from api_handler.routes import accounts
        events = fake_events([other_statement()])

        def _drops_others(EventBusName, Policy=None, **_):
            events.statements["statements"] = [
                x for x in json.loads(Policy)["Statement"] if x["Sid"] == "acct-222233334444"]
        events.put_permission.side_effect = _drops_others
        with patch.object(accounts, "send_error_alert") as alert:
            resp, table = _create(_body(), events)
        assert resp["statusCode"] == 201
        assert table.put_item.call_args.kwargs["Item"]["alert_forwarding"] == "grant_failed"
        alert.assert_called_once()

    def test_successful_registration_stays_quiet(self):
        from api_handler.routes import accounts
        with patch.object(accounts, "send_error_alert") as alert:
            resp, _ = _create(_body(), fake_events())
        assert resp["statusCode"] == 201
        alert.assert_not_called()


# ──────────────────────────────────────────────
# 2026-09-22 — 알람 삭제는 우리가 태그한 알람에만.
# 첫 실고객 계정(알람 166개, 전부 고객이 만든 것)을 등록하기 직전에 발견: 중앙 역할에는 처음부터 있던
# ManagedBy 조건이 **고객사 온보딩 역할에는 없었다**. daily monitor는 고객 계정을 처리할 때 그 역할을
# 뒤집어쓰므로, 고객 알람과 우리 알람을 가르는 것이 이름·설명 휴리스틱 하나뿐이었다(AP-18/AP-19).
# ──────────────────────────────────────────────

TEMPLATES = ("infrastructure/backend/template.yaml", "infrastructure/customer-onboarding/template.yaml",
             "frontend/public/customer-onboarding.yaml")


def _roles_that_delete_alarms(rel: str):
    import pathlib
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def any_tag(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    Loader.add_multi_constructor("!", any_tag)
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = yaml.load((root / rel).read_text(encoding="utf-8"), Loader=Loader)
    found = []
    for name, res in doc["Resources"].items():
        if res.get("Type") != "AWS::IAM::Role":
            continue
        for policy in res.get("Properties", {}).get("Policies") or []:
            for st in policy["PolicyDocument"]["Statement"]:
                actions = st.get("Action")
                actions = actions if isinstance(actions, list) else [actions]
                if "cloudwatch:DeleteAlarms" in actions:
                    found.append((name, st.get("Condition")))
    return found


class TestDeleteAlarmsIsTagGated:
    @pytest.mark.parametrize("rel", ["infrastructure/customer-onboarding/template.yaml",
                                     "frontend/public/customer-onboarding.yaml"])
    def test_customer_role_can_only_delete_alarms_it_manages(self, rel):
        roles = _roles_that_delete_alarms(rel)
        assert roles, f"{rel}: 알람 삭제 권한을 가진 역할이 있어야 한다"
        for name, condition in roles:
            assert condition == {"StringEquals": {"aws:ResourceTag/ManagedBy": "AlarmManager"}}, \
                f"{rel}:{name} — 고객 계정에서 태그 조건 없는 DeleteAlarms는 남의 알람까지 지울 수 있다"

    def test_the_daily_monitor_role_keeps_its_guard(self):
        roles = dict(_roles_that_delete_alarms("infrastructure/backend/template.yaml"))
        assert roles["MonitoringEngineRole"] == {
            "StringEquals": {"aws:ResourceTag/ManagedBy": "AlarmManager"}}

    def test_the_two_published_copies_match_the_source(self):
        """공개 S3 사본은 손으로 올린다 — 소스와 갈라지면 원클릭 배포가 옛 권한을 만든다."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / "infrastructure/customer-onboarding/template.yaml").read_text(encoding="utf-8")
        published = (root / "frontend/public/customer-onboarding.yaml").read_text(encoding="utf-8")
        assert source == published
