"""
/alert/incidents — 목록·조회·확인 (requirements R4, tasks 2.1.3~2.1.4)

핵심은 **확인이 한 번만 기록되는 것**이다(R4-3). 두 번째 확인이 시각을 덮으면 MTTA가
거짓이 되고 "누가 먼저 잡았나"라는 기록의 목적도 사라진다.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from test_api_handler import _event
from common.incident import acknowledge, merge_events, new_incident, resolve, to_item

T0 = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)
ME = "oncall@mz.co.kr"


class FakeIncidentTable:
    """조건부 PutItem을 해석한다 — 확인의 낙관적 잠금(version)이 여기 걸려 있다."""

    def __init__(self, items=None):
        self.items = {i["incident_id"]: dict(i) for i in (items or [])}

    def get_item(self, Key, **_):
        it = self.items.get(Key["incident_id"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        from fakes_ddb import _eval, conditional_failure
        cur = self.items.get(Item["incident_id"])
        if ConditionExpression is not None and not _eval(ConditionExpression, cur):
            raise conditional_failure()
        self.items[Item["incident_id"]] = dict(Item)

    def query(self, KeyConditionExpression=None, **_):
        wanted = KeyConditionExpression.get_expression()["values"][1]
        rows = [dict(v) for v in self.items.values() if v.get("customer_id") == wanted]
        return {"Items": rows}


def incident(*, status="triggered", customer="cust-1", severity="SEV-2",
             acked_at=None, acked_by=None, resolved_at=None, iid=None, **over):
    inc = new_incident(customer, severity, now=T0, title="[EC2] i-1 CPU > 80%")
    inc = merge_events(inc, [{"series_id": "111#i-1#CPU", "alarm_name": "[EC2] i-1"}], now=T0)
    if status == "acknowledged":
        inc = acknowledge(inc, by=acked_by or "first@mz.co.kr", now=T0 + timedelta(minutes=3))
    elif status == "resolved":
        inc = resolve(inc, now=T0 + timedelta(minutes=10))
    if iid:
        inc["incident_id"] = iid
    inc.update(over)
    return to_item(inc, now=T0)


def call(method, path, *, table=None, qs=None, path_params=None, email=ME, body=None):
    from api_handler.routes import incidents as mod
    table = table if table is not None else FakeIncidentTable()
    ev = _event(method, path, body=body, qs=qs, path_params=path_params)
    ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": email}}} if email else {}
    with patch.object(mod, "incident_table", return_value=table), \
         patch.object(mod, "scan_all", side_effect=lambda t: list(t.items.values())):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(ev, None)
    return resp, json.loads(resp["body"] or "{}"), table


class TestAcknowledge:
    def test_records_the_caller_and_computes_mtta(self):
        table = FakeIncidentTable([incident(iid="inc-1")])
        resp, b, t = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 200, resp["body"]
        assert b["status"] == "acknowledged" and b["acknowledged_by"] == ME
        assert isinstance(b["mtta_sec"], int)
        assert t.items["inc-1"]["acknowledged_by"] == ME

    def test_identity_comes_from_the_session_not_the_body(self):
        """본문으로 받으면 남을 대신 확인할 수 있다."""
        table = FakeIncidentTable([incident(iid="inc-1")])
        _, b, _ = call("POST", "/alert/incidents/inc-1/ack", table=table,
                       path_params={"id": "inc-1"},
                       body={"acknowledged_by": "someone-else@evil.com"})
        assert b["acknowledged_by"] == ME

    def test_second_ack_keeps_the_first_person(self):
        table = FakeIncidentTable([incident(iid="inc-1", status="acknowledged",
                                            acked_by="first@mz.co.kr")])
        resp, b, _ = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 200
        assert b["acknowledged_by"] == "first@mz.co.kr"

    def test_resolved_incident_is_a_conflict(self):
        table = FakeIncidentTable([incident(iid="inc-1", status="resolved")])
        resp, b, _ = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 409 and b["code"] == "ALREADY_RESOLVED"

    def test_missing_incident_is_a_404(self):
        resp, _, _ = call("POST", "/alert/incidents/nope/ack", path_params={"id": "nope"})
        assert resp["statusCode"] == 404

    def test_unknown_caller_is_refused(self):
        table = FakeIncidentTable([incident(iid="inc-1")])
        resp, b, _ = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"}, email="")
        assert resp["statusCode"] in (401, 403)

    def test_storage_failure_is_surfaced(self):
        from api_handler.routes import incidents as mod
        table = MagicMock()
        table.get_item.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetItem")
        ev = _event("POST", "/alert/incidents/inc-1/ack", path_params={"id": "inc-1"})
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": ME}}}
        with patch.object(mod, "incident_table", return_value=table):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(ev, None)
        assert resp["statusCode"] == 503

    # ── 확인은 읽은 버전일 때만 저장된다 (review-phase2 H2) — 라우터가 같은 순간 합치고 있다

    def test_ack_is_reapplied_on_top_of_a_concurrent_merge(self):
        """읽은 뒤 라우터가 구성원을 더했다 → 확인은 그 위에 얹히고 새 구성원도 남는다."""
        class MergeRacing(FakeIncidentTable):
            def __init__(self, items):
                super().__init__(items)
                self.raced = False

            def put_item(self, Item, ConditionExpression=None, **kw):
                if not self.raced:
                    self.raced = True
                    row = self.items["inc-1"]
                    row["members"] = list(row["members"]) + ["111#i-2#CPU"]
                    row["version"] = int(row.get("version", 0)) + 1
                return super().put_item(Item, ConditionExpression=ConditionExpression, **kw)

        table = MergeRacing([{**incident(iid="inc-1"), "version": 1}])
        resp, b, t = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 200, resp["body"]
        row = t.items["inc-1"]
        assert row["status"] == "acknowledged" and row["acknowledged_by"] == ME
        assert set(row["members"]) == {"111#i-1#CPU", "111#i-2#CPU"}, "합쳐진 구성원이 사라지면 조기 해소된다"
        assert row["version"] == 3 and b["version"] == 3

    def test_persistent_conflict_is_a_409_not_a_silent_overwrite(self):
        class AlwaysRacing(FakeIncidentTable):
            def put_item(self, Item, ConditionExpression=None, **kw):
                self.items["inc-1"]["version"] = int(self.items["inc-1"].get("version", 0)) + 1
                return super().put_item(Item, ConditionExpression=ConditionExpression, **kw)

        table = AlwaysRacing([{**incident(iid="inc-1"), "version": 1}])
        resp, b, t = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 409 and b["code"] == "CONFLICT"
        assert t.items["inc-1"]["status"] == "triggered"

    def test_legacy_row_without_a_version_is_acknowledged(self):
        """버전을 붙이기 전의 행 — 0으로 읽고 1로 쓴다."""
        table = FakeIncidentTable([incident(iid="inc-1")])
        assert "version" not in table.items["inc-1"]
        resp, b, t = call("POST", "/alert/incidents/inc-1/ack", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 200 and t.items["inc-1"]["version"] == 1


class TestListing:
    def test_returns_incidents_newest_first(self):
        old = incident(iid="old")
        new = incident(iid="new")
        new["triggered_at"] = "2026-09-09T12:00:00Z"
        resp, b, _ = call("GET", "/alert/incidents", table=FakeIncidentTable([old, new]))
        assert resp["statusCode"] == 200
        assert [i["incident_id"] for i in b["incidents"]] == ["new", "old"]

    def test_customer_filter_uses_the_index(self):
        table = FakeIncidentTable([incident(iid="a", customer="cust-1"),
                                   incident(iid="b", customer="cust-2")])
        _, b, _ = call("GET", "/alert/incidents", table=table, qs={"customer_id": "cust-1"})
        assert [i["incident_id"] for i in b["incidents"]] == ["a"]

    def test_status_filter(self):
        table = FakeIncidentTable([incident(iid="t"),
                                   incident(iid="r", status="resolved")])
        _, b, _ = call("GET", "/alert/incidents", table=table, qs={"status": "resolved"})
        assert [i["incident_id"] for i in b["incidents"]] == ["r"]

    def test_summary_reports_mtta_and_mttr(self):
        acked = incident(iid="a", status="acknowledged")
        done = incident(iid="r", status="resolved")
        _, b, _ = call("GET", "/alert/incidents", table=FakeIncidentTable([acked, done]))
        s = b["summary"]
        assert s["total"] == 2
        assert s["acknowledged_count"] == 1 and s["resolved_count"] == 1
        assert s["mtta_sec_avg"] == 180.0 and s["mttr_sec_avg"] == 600.0

    def test_summary_counts_everything_even_when_the_list_is_capped(self):
        table = FakeIncidentTable([incident(iid=f"i{i}") for i in range(5)])
        _, b, _ = call("GET", "/alert/incidents", table=table, qs={"limit": "2"})
        assert len(b["incidents"]) == 2 and b["truncated"] is True
        assert b["summary"]["total"] == 5

    def test_empty(self):
        resp, b, _ = call("GET", "/alert/incidents")
        assert resp["statusCode"] == 200 and b["summary"]["total"] == 0


class TestGetOne:
    def test_returns_the_timeline(self):
        table = FakeIncidentTable([incident(iid="inc-1")])
        resp, b, _ = call("GET", "/alert/incidents/inc-1", table=table,
                          path_params={"id": "inc-1"})
        assert resp["statusCode"] == 200
        assert b["incident_id"] == "inc-1"
        assert [t["kind"] for t in b["timeline"]] == ["triggered", "alarm"]
        assert b["members"] == ["111#i-1#CPU"]

    def test_missing_is_a_404(self):
        resp, _, _ = call("GET", "/alert/incidents/nope", path_params={"id": "nope"})
        assert resp["statusCode"] == 404
