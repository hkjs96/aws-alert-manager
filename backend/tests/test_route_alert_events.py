"""
GET /alert/events — 알림 처리 결과 조회 (review-personas F7)

"알람은 울렸는데 왜 안 왔지"에 답하는 화면의 데이터원. 고정하는 것:
- 기간은 고객사×일 GSI로 읽고, **고객사 매핑이 없는 파티션도** 포함한다(미등록 계정 알람이 사라지면 안 된다)
- 요약은 필터 적용 후·건수 제한 전 값이다(화면 요약이 목록 일부만 세면 안 된다)
- 격리(flapping)는 해제 시각을 함께 준다
- 상태 테이블이 없거나 실패해도 조회 자체는 성공한다
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from test_api_handler import _event

TODAY = datetime.now(timezone.utc).date().isoformat()
YESTERDAY = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "event-history-test")
    monkeypatch.setenv("ALERT_STATE_TABLE", "alert-state-test")
    yield


def row(series="111#i-1#CPU", *, day=None, at=None, suppressed=False, reason="",
        final=None, final_reason="", customer="cust-1", **over):
    at = at or f"{day or TODAY}T10:15:30Z"
    item = {
        "series_id": series, "event_key": f"{at}#abc", "customer_day": f"{customer}#{at[:10]}",
        "event_type": "state_change", "state": "ALARM", "previous_state": "OK",
        "occurred_at": at, "customer_id": customer, "account_id": "111",
        "alarm_name": "[EC2] web CPUUtilization > 80% (TagName: i-1)",
        "resource_id": "i-1", "resource_type": "EC2", "metric_key": "CPUUtilization",
        "severity": "SEV-3", "suppressed": suppressed,
    }
    if reason:
        item["suppression_reason"] = reason
    if final:
        item["final_action"] = final
        item["final_reason"] = final_reason
    item.update(over)
    return item


def call(items, *, qs=None, customers=("cust-1",), state_items=None, hist_error=None):
    from api_handler.routes import alert_events
    hist, state = MagicMock(), MagicMock()
    if hist_error:
        hist.query.side_effect = hist_error
    else:
        def _query(**kw):
            wanted = kw["KeyConditionExpression"].get_expression()["values"][1]
            return {"Items": [i for i in items if i.get("customer_day") == wanted]}
        hist.query.side_effect = _query
    state.get_item.side_effect = lambda Key, **_: (
        {"Item": (state_items or {}).get(Key["state_key"])}
        if (state_items or {}).get(Key["state_key"]) else {})

    with patch.object(alert_events, "event_history_table", return_value=hist), \
         patch.object(alert_events, "alert_state_table", return_value=state), \
         patch.object(alert_events, "scan_all",
                      return_value=[{"customer_id": c} for c in customers]), \
         patch.object(alert_events, "customers_table", return_value=MagicMock()):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("GET", "/alert/events", qs=qs or {}), None)
    return resp, json.loads(resp["body"]), hist, state


class TestVerdictsAreVisible:
    def test_each_event_carries_a_human_reason(self):
        resp, body, _, _ = call([row(suppressed=True, reason="dedup")])
        assert resp["statusCode"] == 200
        e = body["events"][0]
        assert e["action"] == "suppress" and e["action_label"] == "억제"
        assert e["reason"] == "dedup" and e["reason_label"] == "중복 병합"
        assert e["explanation"]

    def test_group_writeback_wins_over_ingest_verdict(self):
        _, body, _, _ = call([row(suppressed=True, reason="auto_pause",
                                  final="notify", final_reason="auto_pause_expired")])
        e = body["events"][0]
        assert (e["action"], e["reason_label"], e["finalized"]) == ("notify", "유예 후 발송", True)

    def test_pending_is_distinct_from_suppressed(self):
        _, body, _, _ = call([row(reason="auto_pause")])
        assert body["events"][0]["action"] == "pending"
        assert body["summary"]["pending"] == 1

    def test_alarm_identity_fields_are_present(self):
        _, body, _, _ = call([row()])
        e = body["events"][0]
        for f in ("occurred_at", "alarm_name", "resource_id", "resource_type",
                  "metric_key", "severity", "state", "previous_state", "kind"):
            assert e[f], f
        assert e["kind"] == "firing"


class TestSummary:
    def test_counts_and_suppression_rate(self):
        items = [row(series=f"111#i-{i}#CPU", suppressed=True, reason="dedup") for i in range(3)]
        items += [row(series="111#i-9#CPU")]
        _, body, _, _ = call(items)
        s = body["summary"]
        assert (s["total"], s["notify"], s["suppress"]) == (4, 1, 3)
        assert s["suppression_rate"] == 0.75

    def test_pending_is_excluded_from_the_rate(self):
        """확정되지 않은 건을 분모에 넣으면 억제율이 흔들린다."""
        _, body, _, _ = call([row(reason="auto_pause"), row(series="111#i-2#CPU")])
        assert body["summary"]["suppression_rate"] == 0.0

    def test_empty_is_zero_not_an_error(self):
        resp, body, _, _ = call([])
        assert resp["statusCode"] == 200
        assert body["summary"]["total"] == 0 and body["summary"]["suppression_rate"] == 0.0

    def test_summary_counts_everything_even_when_the_list_is_capped(self):
        items = [row(series=f"111#i-{i}#CPU", suppressed=True, reason="dedup") for i in range(5)]
        _, body, _, _ = call(items, qs={"limit": "2"})
        assert len(body["events"]) == 2 and body["truncated"] is True
        assert body["summary"]["total"] == 5

    def test_summary_reflects_resource_filter(self):
        _, body, _, _ = call([row(), row(series="111#i-2#CPU", resource_id="i-2")],
                             qs={"resource_id": "i-2"})
        assert body["summary"]["total"] == 1


class TestQueryScope:
    def test_unmapped_customer_partition_is_included(self):
        """미등록 계정 이벤트는 `#날짜` 파티션에 쌓인다 — 빠뜨리면 화면에서 통째로 사라진다."""
        _, body, hist, _ = call([row(customer="", resource_id="i-orphan")])
        queried = {c.kwargs["KeyConditionExpression"].get_expression()["values"][1]
                   for c in hist.query.call_args_list}
        assert f"#{TODAY}" in queried
        assert body["summary"]["total"] == 1

    def test_explicit_customer_narrows_the_query(self):
        _, _, hist, _ = call([], qs={"customer_id": "cust-9"}, customers=("cust-1", "cust-2"))
        queried = {c.kwargs["KeyConditionExpression"].get_expression()["values"][1]
                   for c in hist.query.call_args_list}
        assert queried == {f"cust-9#{TODAY}"}

    def test_days_expands_the_range(self):
        _, body, hist, _ = call([row(), row(series="111#i-2#CPU", day=YESTERDAY)],
                                qs={"days": "2"})
        queried = {c.kwargs["KeyConditionExpression"].get_expression()["values"][1]
                   for c in hist.query.call_args_list}
        assert {f"cust-1#{TODAY}", f"cust-1#{YESTERDAY}"} <= queried
        assert body["summary"]["total"] == 2

    def test_days_is_clamped(self):
        _, body, _, _ = call([], qs={"days": "999"})
        assert body["days"] == 14

    def test_garbage_params_fall_back_to_defaults(self):
        _, body, _, _ = call([], qs={"days": "abc", "limit": "xyz"})
        assert body["days"] == 1 and body["limit"] == 100

    def test_pagination_of_a_single_day_is_followed(self):
        from api_handler.routes import alert_events
        hist = MagicMock()
        hist.query.side_effect = [
            {"Items": [row()], "LastEvaluatedKey": {"k": 1}},
            {"Items": [row(series="111#i-2#CPU")]},
        ]
        with patch.object(alert_events, "event_history_table", return_value=hist), \
             patch.object(alert_events, "alert_state_table", return_value=MagicMock()), \
             patch.object(alert_events, "scan_all", return_value=[{"customer_id": "cust-1"}]), \
             patch.object(alert_events, "customers_table", return_value=MagicMock()):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/alert/events", qs={"customer_id": "cust-1"}), None)
        assert json.loads(resp["body"])["summary"]["total"] == 2


class TestFilters:
    def test_action_filter(self):
        _, body, _, _ = call([row(suppressed=True, reason="dedup"), row(series="111#i-2#CPU")],
                             qs={"action": "suppress"})
        assert [e["action"] for e in body["events"]] == ["suppress"]

    def test_invalid_action_is_rejected(self):
        resp, body, _, _ = call([], qs={"action": "nope"})
        assert resp["statusCode"] == 400 and body["code"] == "VALIDATION_ERROR"

    def test_newest_first(self):
        early = row(series="111#i-1#CPU", at=f"{TODAY}T01:00:00Z")
        late = row(series="111#i-2#CPU", at=f"{TODAY}T23:00:00Z")
        _, body, _, _ = call([early, late])
        assert [e["resource_id"] for e in body["events"]][0] == late["resource_id"]
        assert body["events"][0]["occurred_at"] > body["events"][1]["occurred_at"]


class TestQuarantine:
    def test_flapping_rows_show_when_the_silence_ends(self):
        until = "2026-09-08T12:00:00Z"
        _, body, _, _ = call(
            [row(suppressed=True, reason="flapping")],
            state_items={"fp#111#i-1#CPU": {"quarantined_until": until}})
        assert body["events"][0]["quarantined_until"] == until

    def test_other_reasons_do_not_read_state(self):
        _, _, _, state = call([row(suppressed=True, reason="dedup")])
        state.get_item.assert_not_called()

    def test_state_failure_does_not_break_the_listing(self):
        from api_handler.routes import alert_events
        hist, state = MagicMock(), MagicMock()
        hist.query.return_value = {"Items": [row(suppressed=True, reason="flapping")]}
        state.get_item.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetItem")
        with patch.object(alert_events, "event_history_table", return_value=hist), \
             patch.object(alert_events, "alert_state_table", return_value=state), \
             patch.object(alert_events, "scan_all", return_value=[{"customer_id": "cust-1"}]), \
             patch.object(alert_events, "customers_table", return_value=MagicMock()):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alert/events", qs={}), None)
        assert resp["statusCode"] == 200
        assert "quarantined_until" not in json.loads(resp["body"])["events"][0]


class TestFailures:
    def test_history_read_failure_is_surfaced(self):
        resp, body, _, _ = call([], hist_error=ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "Query"))
        assert resp["statusCode"] == 503 and body["code"] == "STORAGE_ERROR"

    def test_missing_table_config_is_reported(self, monkeypatch):
        monkeypatch.delenv("EVENT_HISTORY_TABLE", raising=False)
        resp, body, _, _ = call([])
        assert resp["statusCode"] == 503 and body["code"] == "NOT_CONFIGURED"
