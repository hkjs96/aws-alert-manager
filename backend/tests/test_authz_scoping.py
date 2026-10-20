"""유저별 고객사 범위 (docs/specs/authz-scoping/design.md).

고객사 A(담당 alice, 계정 111)와 B(담당 bob, 계정 222), 고객사 없는 계정 999의 데이터를 두고 네 신원으로 본다:
- ``admin``  — ADMIN_EMAILS의 관리자: 전부
- ``alice``  — A의 담당자: A 것만, B 단건은 404
- ``nobody`` — 담당 고객사 없음: 아무것도
- ``open``   — ADMIN_EMAILS 미설정: 제한 없음(기존 동작)
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from api_handler import authz
from api_handler.authz import Scope, scope_for

ADMIN = "boss@mz.co.kr"
ALICE = "alice@mz.co.kr"
NOBODY = "carol@mz.co.kr"

CUSTOMERS = [
    {"customer_id": "A", "name": "Alpha", "managers": ["Alice@mz.co.kr"]},
    {"customer_id": "B", "name": "Beta", "managers": ["bob@mz.co.kr"]},
]
ACCOUNTS = [
    {"customer_id": "A", "account_id": "111", "name": "a-prod", "role_arn": "arn:aws:iam::111:role/r"},
    {"customer_id": "B", "account_id": "222", "name": "b-prod", "role_arn": "arn:aws:iam::222:role/r"},
]
INVENTORY = [
    {"resource_id": "i-a", "account_id": "111", "customer_id": "A", "entity_type": "resource",
     "type": "EC2", "name": "a-web", "monitoring": True},
    {"resource_id": "i-b", "account_id": "222", "customer_id": "B", "entity_type": "resource",
     "type": "EC2", "name": "b-web", "monitoring": True},
    {"resource_id": "i-c", "account_id": "999", "entity_type": "resource",
     "type": "EC2", "name": "central", "monitoring": False},
    {"resource_id": "alarm#a", "account_id": "111", "entity_type": "alarm", "resource": "i-a",
     "alarm_name": "a-cpu", "state": "ALARM", "type": "EC2", "metric": "CPUUtilization"},
    {"resource_id": "alarm#b", "account_id": "222", "entity_type": "alarm", "resource": "i-b",
     "alarm_name": "b-cpu", "state": "ALARM", "type": "EC2", "metric": "CPUUtilization"},
]
MODES = ("admin", "alice", "nobody", "open")
EXPECTED_CUSTOMERS = {"admin": {"A", "B"}, "alice": {"A"}, "nobody": set(), "open": {"A", "B"}}


def _scan(table):
    return [dict(i) for i in {"customers": CUSTOMERS, "accounts": ACCOUNTS, "inventory": INVENTORY}[table]]


@pytest.fixture
def as_user(monkeypatch):
    """신원 모드를 정하고, 범위 계산이 읽는 고객사·계정 테이블을 가짜로 둔다. 이벤트 생성기를 돌려준다."""
    monkeypatch.setattr(authz, "customers_table", lambda: "customers")
    monkeypatch.setattr(authz, "accounts_table", lambda: "accounts")
    monkeypatch.setattr(authz, "scan_all", _scan)

    def make(mode, *, qs=None, path=None, body=None):
        if mode == "open":
            monkeypatch.delenv("ADMIN_EMAILS", raising=False)
        else:
            monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
        email = {"admin": ADMIN, "alice": ALICE, "nobody": NOBODY, "open": ALICE}[mode]
        return {
            "requestContext": {"http": {"method": "GET"},
                               "authorizer": {"jwt": {"claims": {"email": email}}}},
            "queryStringParameters": qs or {},
            "pathParameters": path or {},
            "body": json.dumps(body) if body is not None else None,
        }
    return make


def _body(resp):
    return json.loads(resp["body"] or "{}")


# ── 범위 의미 ─────────────────────────────────────────────────────

class TestScopeSemantics:
    def test_admin_is_unrestricted(self, as_user):
        assert scope_for(as_user("admin")).unrestricted

    def test_no_admin_emails_is_unrestricted(self, as_user):
        assert scope_for(as_user("open")).unrestricted

    def test_no_email_with_admins_configured_sees_nothing(self, monkeypatch):
        """신원 없는 요청은 닫는 쪽으로 실패한다(인증이 켜져 있으면 생길 수 없는 경우)."""
        monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
        s = scope_for({"requestContext": {}})
        assert not s.unrestricted and not s.customer_ids and not s.allows_item({"customer_id": "A"})

    def test_manager_sees_own_customer_and_accounts(self, as_user):
        s = scope_for(as_user("alice"))
        assert not s.unrestricted
        assert s.customer_ids == {"A"} and s.account_ids == {"111"}
        assert s.allows_customer("A") and not s.allows_customer("B")
        assert s.allows_account("111") and not s.allows_account("222")

    def test_non_manager_sees_nothing(self, as_user):
        s = scope_for(as_user("nobody"))
        assert not s.unrestricted and not s.customer_ids and not s.account_ids
        assert s.filter(_scan("inventory")) == []

    def test_item_without_customer_is_admin_only(self, as_user):
        central = {"resource_id": "i-c", "account_id": "999"}
        assert not scope_for(as_user("alice")).allows_item(central)
        assert not scope_for(as_user("alice")).allows_item({"resource_id": "x"})
        assert scope_for(as_user("admin")).allows_item(central)

    def test_alarm_row_reached_through_account(self, as_user):
        s = scope_for(as_user("alice"))
        assert s.allows_item({"entity_type": "alarm", "account_id": "111"})
        assert not s.allows_item({"entity_type": "alarm", "account_id": "222"})

    def test_lookup_failure_gives_empty_scope(self, as_user, monkeypatch):
        event = as_user("alice")

        def boom(_):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "Scan")
        monkeypatch.setattr(authz, "scan_all", boom)
        s = scope_for(event)
        assert not s.unrestricted and not s.customer_ids and not s.allows_customer("A")


# ── 리소스 ────────────────────────────────────────────────────────

@pytest.fixture
def inventory(monkeypatch):
    from api_handler.routes import resources
    monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "inv")
    monkeypatch.setattr(resources, "resource_inventory_table", lambda: "inventory")
    monkeypatch.setattr(resources, "scan_all", _scan)
    monkeypatch.setattr(resources, "query_by_pk",
                        lambda t, k, v: [i for i in _scan("inventory") if i["resource_id"] == v])
    return resources


class TestResources:
    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"i-a", "i-b", "i-c"}), ("alice", {"i-a"}), ("nobody", set()), ("open", {"i-a", "i-b", "i-c"}),
    ])
    def test_list(self, as_user, inventory, mode, expected):
        resp = inventory.list_resources(as_user(mode))
        assert {i["id"] for i in _body(resp)["items"]} == expected

    @pytest.mark.parametrize("mode,rid,status", [
        ("alice", "i-a", 200), ("alice", "i-b", 404), ("alice", "i-c", 404), ("nobody", "i-a", 404),
        ("admin", "i-b", 200), ("open", "i-c", 200),
    ])
    def test_detail(self, as_user, inventory, mode, rid, status):
        assert inventory.get_resource(as_user(mode, path={"id": rid}))["statusCode"] == status

    def test_resource_alarms_hide_other_customer(self, as_user, inventory):
        assert _body(inventory.get_resource_alarms(as_user("alice", path={"id": "i-b"}))) == []
        assert len(_body(inventory.get_resource_alarms(as_user("alice", path={"id": "i-a"})))) == 1
        assert len(_body(inventory.get_resource_alarms(as_user("admin", path={"id": "i-b"})))) == 1

    def test_metrics_out_of_scope_is_404(self, as_user, inventory):
        assert inventory.get_resource_metrics(as_user("alice", path={"id": "i-b"}))["statusCode"] == 404

    def test_disk_paths_and_overlaps_out_of_scope_are_404(self, as_user, inventory):
        assert inventory.get_disk_paths(as_user("alice", path={"id": "i-b"}))["statusCode"] == 404
        assert inventory.get_alarm_overlaps(as_user("nobody", path={"id": "i-a"}))["statusCode"] == 404

    def test_monitoring_toggle_out_of_scope_is_404_and_writes_nothing(self, as_user, inventory, monkeypatch):
        tag = MagicMock()
        monkeypatch.setattr(inventory, "_set_resource_monitoring_tag", tag)
        resp = inventory.update_resource_monitoring(
            as_user("alice", path={"id": "i-b"}, body={"monitoring": False}))
        assert resp["statusCode"] == 404
        tag.assert_not_called()

    @pytest.mark.parametrize("handler,body", [
        ("create_resource_alarm", {"metric_name": "CPUUtilization", "threshold": 80}),
        ("update_resource_alarms", {"configs": []}),
    ])
    def test_alarm_writes_out_of_scope_are_404(self, as_user, inventory, monkeypatch, handler, body):
        cw_list = MagicMock(return_value=[])
        monkeypatch.setattr(inventory, "list_alarms", cw_list)
        resp = getattr(inventory, handler)(as_user("alice", path={"id": "i-b"}, body=body))
        assert resp["statusCode"] == 404
        cw_list.assert_not_called()

    def test_alarm_writes_unrestricted_skip_the_scope_lookup(self, as_user, inventory, monkeypatch):
        lookup = MagicMock(side_effect=AssertionError("no scope lookup when unrestricted"))
        monkeypatch.setattr(inventory, "query_by_pk", lookup)
        monkeypatch.setattr(inventory, "list_alarms", MagicMock(return_value=[]))
        resp = inventory.update_resource_alarms(as_user("open", path={"id": "i-b"}, body={"configs": []}))
        assert resp["statusCode"] == 404           # 기존 동작: CW 알람이 없으면 404
        lookup.assert_not_called()


# ── 알람·대시보드 ─────────────────────────────────────────────────

class TestAlarmsAndDashboard:
    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"a-cpu", "b-cpu"}), ("alice", {"a-cpu"}), ("nobody", set()), ("open", {"a-cpu", "b-cpu"}),
    ])
    def test_alarm_list_and_summary(self, as_user, monkeypatch, mode, expected):
        from api_handler.routes import alarms
        monkeypatch.setattr(alarms, "resource_inventory_table", lambda: "inventory")
        monkeypatch.setattr(alarms, "scan_all", _scan)
        listed = _body(alarms.list_alarms_handler(as_user(mode)))
        assert {i["alarm_name"] for i in listed["items"]} == expected
        assert _body(alarms.get_alarm_summary(as_user(mode)))["alarm_count"] == len(expected)

    @pytest.mark.parametrize("mode,monitored,active,accounts", [
        ("admin", 2, 2, 2), ("alice", 1, 1, 1), ("nobody", 0, 0, 0), ("open", 2, 2, 2),
    ])
    def test_dashboard(self, as_user, monkeypatch, mode, monitored, active, accounts):
        from api_handler import db
        from api_handler.routes import dashboard
        monkeypatch.setattr(db, "resource_inventory_table", lambda: "inventory")
        monkeypatch.setattr(db, "accounts_table", lambda: "accounts")
        monkeypatch.setattr(db, "scan_all", _scan)
        stats = _body(dashboard.get_stats(as_user(mode)))
        assert (stats["monitored_count"], stats["active_alarms"], stats["account_count"]) == \
            (monitored, active, accounts)
        recent = _body(dashboard.get_recent_alarms(as_user(mode)))
        assert recent["total"] == active


# ── 고객사 ────────────────────────────────────────────────────────

class FakeCustomers:
    def __init__(self, items):
        self.items = {i["customer_id"]: dict(i) for i in items}

    def get_item(self, Key):
        it = self.items.get(Key["customer_id"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item):
        self.items[Item["customer_id"]] = dict(Item)

    def delete_item(self, Key):
        self.items.pop(Key["customer_id"], None)


@pytest.fixture
def customers(monkeypatch):
    from api_handler import db
    from api_handler.routes import customers as mod
    from api_handler.routes import preferences
    table = FakeCustomers(CUSTOMERS)
    monkeypatch.setattr(mod, "customers_table", lambda: table)
    monkeypatch.setattr(mod, "accounts_table", lambda: "accounts")
    monkeypatch.setattr(db, "scan_all", lambda t: list(t.items.values()) if isinstance(t, FakeCustomers) else _scan(t))
    monkeypatch.setattr(preferences, "add_owned_customer", MagicMock())
    return mod, table


class TestCustomers:
    @pytest.mark.parametrize("mode", MODES)
    def test_list(self, as_user, customers, mode):
        mod, _ = customers
        items = _body(mod.list_customers(as_user(mode)))
        assert {i["customer_id"] for i in items} == EXPECTED_CUSTOMERS[mode]
        assert all(isinstance(i["managers"], list) for i in items)

    def test_create_makes_creator_a_manager(self, as_user, customers):
        mod, table = customers
        resp = mod.create_customer(as_user("nobody", body={"name": "Gamma", "code": "C"}))
        assert resp["statusCode"] == 201
        assert table.items["C"]["managers"] == [NOBODY]

    def test_update_by_manager(self, as_user, customers):
        mod, table = customers
        resp = mod.update_customer(as_user("alice", path={"id": "A"},
                                            body={"name": "Alpha2", "managers": [" Dave@mz.co.kr ", ALICE]}))
        assert resp["statusCode"] == 200
        assert table.items["A"]["name"] == "Alpha2"
        assert table.items["A"]["managers"] == ["dave@mz.co.kr", ALICE]

    @pytest.mark.parametrize("mode,cid", [("alice", "B"), ("nobody", "A"), ("alice", "missing")])
    def test_update_out_of_scope_is_404(self, as_user, customers, mode, cid):
        mod, table = customers
        before = dict(table.items)
        resp = mod.update_customer(as_user(mode, path={"id": cid}, body={"name": "x"}))
        assert resp["statusCode"] == 404
        assert table.items == before

    @pytest.mark.parametrize("mode", ["admin", "open"])
    def test_update_by_admin_or_unrestricted(self, as_user, customers, mode):
        mod, table = customers
        resp = mod.update_customer(as_user(mode, path={"id": "B"}, body={"managers": [ALICE]}))
        assert resp["statusCode"] == 200 and table.items["B"]["managers"] == [ALICE]

    @pytest.mark.parametrize("body", [{"managers": []}, {"managers": ["  "]}, {"managers": "x@y"}, {}])
    def test_update_rejects_empty_managers(self, as_user, customers, body):
        mod, table = customers
        resp = mod.update_customer(as_user("admin", path={"id": "A"}, body=body))
        assert resp["statusCode"] == 400
        assert table.items["A"]["managers"] == ["Alice@mz.co.kr"]

    def test_update_route_is_registered(self):
        from api_handler.lambda_handler import _ROUTES
        from api_handler.routes import customers as mod
        assert any(m == "PUT" and p.match("/customers/A") and h is mod.update_customer for m, p, h in _ROUTES)

    @pytest.mark.parametrize("mode,status", [("alice", 403), ("nobody", 403), ("admin", 204), ("open", 204)])
    def test_delete_is_admin_only(self, as_user, customers, mode, status):
        mod, table = customers
        assert mod.delete_customer(as_user(mode, path={"id": "A"}))["statusCode"] == status
        assert ("A" in table.items) == (status == 403)


# ── 계정 ──────────────────────────────────────────────────────────

@pytest.fixture
def accounts(monkeypatch):
    from api_handler.routes import accounts as mod
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr(mod, "accounts_table", lambda: table)
    monkeypatch.setattr(mod, "scan_all", lambda t: _scan("accounts"))
    monkeypatch.setattr(mod, "query_by_pk",
                        lambda t, k, v: [a for a in _scan("accounts") if a["customer_id"] == v])
    monkeypatch.setattr(mod, "_grant_alert_forwarding", lambda aid: "granted")
    monkeypatch.setattr(mod, "_revoke_alert_forwarding_if_orphan", lambda aid: None)
    return mod, table


class TestAccounts:
    @pytest.mark.parametrize("mode", MODES)
    def test_list(self, as_user, accounts, mode):
        mod, _ = accounts
        assert {a["customer_id"] for a in _body(mod.list_accounts(as_user(mode)))} == EXPECTED_CUSTOMERS[mode]

    def test_list_other_customer_explicitly_is_empty(self, as_user, accounts):
        mod, _ = accounts
        assert _body(mod.list_accounts(as_user("alice", qs={"customer_id": "B"}))) == []

    @pytest.mark.parametrize("mode,cid,status", [
        ("alice", "A", 201), ("alice", "B", 404), ("nobody", "A", 404), ("admin", "B", 201), ("open", "B", 201),
    ])
    def test_create(self, as_user, accounts, mode, cid, status):
        mod, table = accounts
        body = {"account_id": "333", "role_arn": "arn:aws:iam::333:role/r", "name": "n",
                "customer_id": cid, "regions": ["ap-northeast-2"]}
        assert mod.create_account(as_user(mode, body=body))["statusCode"] == status
        assert table.put_item.called == (status == 201)

    @pytest.mark.parametrize("mode,status", [("alice", 403), ("nobody", 403), ("admin", 204), ("open", 204)])
    def test_delete_is_admin_only(self, as_user, accounts, mode, status):
        mod, table = accounts
        resp = mod.delete_account(as_user(mode, path={"id": "111"}, qs={"customer_id": "A"}))
        assert resp["statusCode"] == status
        assert table.delete_item.called == (status == 204)

    def test_test_connection_and_regions_out_of_scope_are_404(self, as_user, accounts):
        mod, table = accounts
        assert mod.test_connection(as_user("alice", path={"id": "222"}, qs={"customer_id": "B"}))["statusCode"] == 404
        resp = mod.update_account_regions(as_user("alice", path={"id": "222"}, qs={"customer_id": "B"},
                                                  body={"regions": ["ap-northeast-2"]}))
        assert resp["statusCode"] == 404
        table.get_item.assert_not_called()
        table.update_item.assert_not_called()

    def test_test_connection_in_scope_reaches_the_table(self, as_user, accounts):
        mod, table = accounts
        resp = mod.test_connection(as_user("alice", path={"id": "111"}, qs={"customer_id": "A"}))
        assert resp["statusCode"] == 404          # 가짜 테이블에 행이 없다 — 범위는 통과했다
        table.get_item.assert_called_once()


# ── 인시던트·이벤트 ───────────────────────────────────────────────

INCIDENTS = [
    {"incident_id": "inc-a", "customer_id": "A", "account_id": "111", "status": "triggered",
     "severity": "SEV-1", "triggered_at": "2026-10-01T00:00:00Z"},
    {"incident_id": "inc-b", "customer_id": "B", "account_id": "222", "status": "triggered",
     "severity": "SEV-1", "triggered_at": "2026-10-01T00:00:00Z"},
]


@pytest.fixture
def incidents(monkeypatch):
    from api_handler.routes import incidents as mod
    table = MagicMock()
    table.get_item.side_effect = lambda Key: {"Item": next(
        (dict(i) for i in INCIDENTS if i["incident_id"] == Key["incident_id"]), None)}
    monkeypatch.setattr(mod, "incident_table", lambda: table)
    monkeypatch.setattr(mod, "scan_all", lambda t: [dict(i) for i in INCIDENTS])
    monkeypatch.setattr(mod, "load", lambda t, iid: (
        next((dict(i) for i in INCIDENTS if i["incident_id"] == iid), None), 1))
    save = MagicMock(side_effect=lambda t, inc, **_: inc)
    monkeypatch.setattr(mod, "save", save)
    return mod, save


class TestIncidents:
    @pytest.mark.parametrize("mode", MODES)
    def test_list(self, as_user, incidents, mode):
        mod, _ = incidents
        listed = _body(mod.list_incidents(as_user(mode)))
        assert {i["customer_id"] for i in listed["incidents"]} == EXPECTED_CUSTOMERS[mode]
        assert listed["summary"]["total"] == len(EXPECTED_CUSTOMERS[mode])

    @pytest.mark.parametrize("mode,iid,status", [
        ("alice", "inc-a", 200), ("alice", "inc-b", 404), ("nobody", "inc-a", 404), ("admin", "inc-b", 200),
        ("open", "inc-b", 200),
    ])
    def test_detail(self, as_user, incidents, mode, iid, status):
        mod, _ = incidents
        assert mod.get_incident(as_user(mode, path={"id": iid}))["statusCode"] == status

    def test_ack_out_of_scope_is_404(self, as_user, incidents):
        mod, save = incidents
        assert mod.ack_incident(as_user("alice", path={"id": "inc-b"}))["statusCode"] == 404
        save.assert_not_called()
        assert mod.ack_incident(as_user("alice", path={"id": "inc-a"}))["statusCode"] == 200
        save.assert_called_once()


class TestAlertEvents:
    EVENTS = {
        "A": [{"event_key": "e-a", "customer_id": "A", "account_id": "111", "occurred_at": "2026-10-20T00:00:00Z"}],
        "B": [{"event_key": "e-b", "customer_id": "B", "account_id": "222", "occurred_at": "2026-10-20T00:00:00Z"}],
        "": [{"event_key": "e-x", "customer_id": "", "account_id": "999", "occurred_at": "2026-10-20T00:00:00Z"}],
    }

    @pytest.fixture
    def events(self, monkeypatch):
        from api_handler.routes import alert_events as mod
        monkeypatch.setenv("EVENT_HISTORY_TABLE", "events")
        monkeypatch.setattr(mod, "customers_table", lambda: "customers")
        monkeypatch.setattr(mod, "scan_all", _scan)
        monkeypatch.setattr(mod, "event_history_table", lambda: "events")
        queried = []

        def query_day(table, cid, day):
            queried.append(cid)
            return [dict(e) for e in self.EVENTS.get(cid, [])]
        monkeypatch.setattr(mod, "_query_day", query_day)
        return mod, queried

    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"e-a", "e-b", "e-x"}), ("alice", {"e-a"}), ("nobody", set()), ("open", {"e-a", "e-b", "e-x"}),
    ])
    def test_list(self, as_user, events, mode, expected):
        mod, _ = events
        rows = _body(mod.list_events(as_user(mode)))["events"]
        assert {r["event_key"] for r in rows} == expected

    def test_out_of_scope_customer_is_not_even_queried(self, as_user, events):
        mod, queried = events
        rows = _body(mod.list_events(as_user("alice", qs={"customer_id": "B"})))["events"]
        assert rows == [] and queried == []


# ── 채널·정비창 ───────────────────────────────────────────────────

class TestChannels:
    @pytest.fixture
    def channels(self, monkeypatch):
        from test_route_notification_channels import FakeTable, stored
        from api_handler.routes import notification_channels as mod
        table = FakeTable([stored("g", ""), stored("ca", "A"), stored("cb", "B")])
        monkeypatch.setattr(mod, "notification_channel_table", lambda: table)
        monkeypatch.setattr(mod, "scan_all", lambda t: list(t.items.values()))
        return mod, table

    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"g", "ca", "cb"}), ("alice", {"g", "ca"}), ("nobody", {"g"}), ("open", {"g", "ca", "cb"}),
    ])
    def test_list_keeps_global_channels_visible(self, as_user, channels, mode, expected):
        mod, _ = channels
        listed = _body(mod.list_channels(as_user(mode)))["channels"]
        assert {c["channel_id"] for c in listed} == expected

    def test_other_customer_channel_writes_are_404(self, as_user, channels):
        mod, table = channels
        before = {k: dict(v) for k, v in table.items.items()}
        body = {"name": "x", "type": "slack", "customer_id": "B",
                "config": {"webhook_url": "https://hooks.slack.com/services/T/B/x"}}
        assert mod.create_channel(as_user("alice", body=body))["statusCode"] == 404
        assert mod.update_channel(as_user("alice", path={"id": "cb"}, body={**body, "name": "y"}))["statusCode"] == 404
        assert mod.delete_channel(as_user("alice", path={"id": "cb"}, qs={"customer_id": "B"}))["statusCode"] == 404
        assert table.items == before

    def test_own_customer_channel_delete_works(self, as_user, channels):
        mod, table = channels
        assert mod.delete_channel(as_user("alice", path={"id": "ca"}, qs={"customer_id": "A"}))["statusCode"] == 204
        assert ("A", "ca") not in table.items


class TestSilences:
    @pytest.fixture
    def silences(self, as_user, monkeypatch):
        from fakes_ddb import FakeConfigTable
        from api_handler.routes import alert_policy as mod
        table = FakeConfigTable()
        monkeypatch.setattr(mod, "alert_policy_table", lambda: table)
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = {}
        for cid in ("", "A", "B"):
            resp = mod.create_silence(as_user("open", body={"ends_at": end, "customer_id": cid}))
            assert resp["statusCode"] == 201
            ids[cid] = _body(resp)["id"]
        return mod, table, ids, end

    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"", "A", "B"}), ("alice", {"", "A"}), ("nobody", {""}), ("open", {"", "A", "B"}),
    ])
    def test_list_keeps_global_silences_visible(self, as_user, silences, mode, expected):
        mod, *_ = silences
        listed = _body(mod.list_silences(as_user(mode)))["silences"]
        assert {s["customer_id"] for s in listed} == expected

    def test_other_customer_silence_writes_are_404(self, as_user, silences):
        mod, table, ids, end = silences
        count = len(table.items)
        assert mod.create_silence(as_user("alice", body={"ends_at": end, "customer_id": "B"}))["statusCode"] == 404
        assert mod.delete_silence(as_user("alice", path={"id": ids["B"]}))["statusCode"] == 404
        assert len(table.items) == count
        assert mod.create_silence(as_user("alice", body={"ends_at": end, "customer_id": "A"}))["statusCode"] == 201
        assert mod.delete_silence(as_user("alice", path={"id": ids["A"]}))["statusCode"] == 200


# ── 임계치 ────────────────────────────────────────────────────────

class TestThresholds:
    @pytest.fixture
    def thresholds(self, monkeypatch):
        from api_handler.routes import thresholds as mod
        table = MagicMock()
        table.query.return_value = {"Items": []}
        monkeypatch.setattr(mod, "threshold_overrides_table", lambda: table)
        return mod, table

    @pytest.mark.parametrize("mode,cid,status", [
        ("alice", "A", 200), ("alice", "B", 404), ("nobody", "A", 404), ("admin", "B", 200), ("open", "B", 200),
    ])
    def test_get_and_put(self, as_user, thresholds, mode, cid, status):
        mod, table = thresholds
        assert mod.get_thresholds(as_user(mode, path={"type": "EC2"}, qs={"customer_id": cid}))["statusCode"] == status
        body = {"customer_id": cid, "overrides": [{"metric_key": "CPU", "customer_override": 90}]}
        assert mod.put_thresholds(as_user(mode, path={"type": "EC2"}, body=body))["statusCode"] == status
        assert table.put_item.called == (status == 200)

    def test_get_without_customer_is_open_to_everyone(self, as_user, thresholds):
        mod, _ = thresholds
        assert mod.get_thresholds(as_user("nobody", path={"type": "EC2"}))["statusCode"] == 200


# ── 동기화·벌크·실행 기록 ─────────────────────────────────────────

class TestSync:
    @pytest.fixture
    def sync(self, monkeypatch):
        from api_handler.routes import sync as mod
        monkeypatch.setenv("DAILY_MONITOR_FUNCTION_NAME", "dm")
        monkeypatch.setattr(mod, "accounts_table", lambda: "accounts")
        monkeypatch.setattr(mod, "scan_all", _scan)
        jobs, lam = MagicMock(), MagicMock()
        monkeypatch.setattr(mod, "job_status_table", lambda: jobs)
        monkeypatch.setattr(mod, "_lambda_client", lambda: lam)
        return mod, lam

    @pytest.mark.parametrize("handler", ["import_resources", "import_alarms"])
    @pytest.mark.parametrize("mode,scope,status", [
        ("alice", {}, 403), ("alice", {"customer_id": "B"}, 404), ("nobody", {"customer_id": "A"}, 404),
        ("alice", {"customer_id": "A"}, 202), ("admin", {}, 202), ("open", {}, 202),
    ])
    def test_scope(self, as_user, sync, handler, mode, scope, status):
        mod, lam = sync
        resp = getattr(mod, handler)(as_user(mode, body={"scope": scope}))
        assert resp["statusCode"] == status
        assert lam.invoke.called == (status == 202)


class TestBulk:
    @pytest.fixture
    def bulk(self, monkeypatch):
        from api_handler.routes import bulk as mod
        monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "inv")
        monkeypatch.setenv("BULK_OPERATION_QUEUE_URL", "q")
        monkeypatch.setattr(mod, "resource_inventory_table", lambda: "inventory")
        monkeypatch.setattr(mod, "scan_all", _scan)
        jobs, sqs = MagicMock(), MagicMock()
        monkeypatch.setattr(mod, "job_status_table", lambda: jobs)
        monkeypatch.setattr(mod, "_get_sqs", lambda: sqs)
        monkeypatch.setattr(mod, "_set_resource_monitoring_tag", MagicMock())
        monkeypatch.setattr(mod, "_update_inventory_monitoring", MagicMock())
        monkeypatch.setattr(mod, "_find_account", lambda aid: None)
        return mod, jobs, sqs

    @pytest.mark.parametrize("mode,ids,status", [
        ("alice", ["i-a", "i-b"], 404), ("alice", ["i-c"], 404), ("nobody", ["i-a"], 404),
        ("alice", ["i-a"], 202), ("admin", ["i-a", "i-b"], 202), ("open", ["i-a", "i-b", "i-c"], 202),
    ])
    def test_any_out_of_scope_rejects_all(self, as_user, bulk, mode, ids, status):
        mod, jobs, sqs = bulk
        resp = mod.bulk_monitoring(as_user(mode, body={"resource_ids": ids, "resource_type": "EC2"}))
        assert resp["statusCode"] == status
        if status == 404:
            jobs.put_item.assert_not_called()
            sqs.send_message.assert_not_called()
        else:
            assert sqs.send_message.call_count == len(ids)


class TestMonitorRuns:
    @pytest.mark.parametrize("mode,expected", [
        ("admin", {"111", "222", ""}), ("alice", {"111"}), ("nobody", set()), ("open", {"111", "222", ""}),
    ])
    def test_filtered_by_account(self, as_user, monkeypatch, mode, expected):
        from api_handler.routes import monitor_runs as mod
        table = MagicMock()
        table.query.return_value = {"Items": [
            {"scope": "daily_monitor", "started_at": f"2026-10-20T0{i}:00:00Z", "account_id": aid, "status": "success"}
            for i, aid in enumerate(["111", "222", ""])]}
        monkeypatch.setattr(mod, "monitor_run_history_table", lambda: table)
        body = _body(mod.list_monitor_runs(as_user(mode)))
        assert {r["account_id"] for r in body["items"]} == expected
        assert body["count"] == len(expected)


class TestMeReturnsVisibleCustomers:
    """/me의 owned_customer_ids는 이제 접근 범위다 — 화면 필터가 백엔드 범위와 어긋나지 않게."""

    def _me(self, scope, customers=()):
        import json
        from unittest.mock import patch
        from api_handler.routes import preferences
        with patch("api_handler.authz.scope_for", return_value=scope), \
             patch("api_handler.db.scan_all", return_value=list(customers)), \
             patch("api_handler.db.customers_table"):
            return json.loads(preferences.get_me({"requestContext": {}})["body"])

    def test_manager_gets_managed_customers(self):
        from api_handler.authz import Scope
        body = self._me(Scope(email="koo@mz.co.kr", unrestricted=False, customer_ids=frozenset({"EMU-EM2"})))
        assert body["owned_customer_ids"] == ["EMU-EM2"]

    def test_admin_gets_every_customer(self):
        from api_handler.authz import Scope
        body = self._me(Scope(email="a@x", unrestricted=True), [{"customer_id": "HOME"}, {"customer_id": "EMU-EM2"}])
        assert body["owned_customer_ids"] == ["EMU-EM2", "HOME"]
