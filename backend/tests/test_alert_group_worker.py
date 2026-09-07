"""
Alert Group Worker (alert_group_worker/lambda_handler.py) 테스트 — design.md D10

- close: 열린 자기 그룹만 닫는다(다른 그룹·이미 닫힘은 무동작)
- collect: 구성원 수, DEFER가 있을 때만 등급별 유예
- finalize: NOTIFY → notify / DEFER+해소 → suppress·auto_pause / DEFER+아직 울림 → notify + 상태에 알렸음
           구성원마다 이력 write-back
"""

from unittest.mock import patch

import pytest

from fakes_ddb import FakeHistoryTable, FakeStateTable
from tests.test_alert_event import state_change_event

SM = "arn:aws:states:us-east-1:111:stateMachine:grp-test"
GROUP = {"group_id": "g-abc-20260902101530", "group_key": "cust-1#SEV-3",
         "customer_id": "cust-1", "severity": "SEV-3", "opened_at": "2026-09-02T10:15:30Z",
         "group_wait_sec": 30}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "event-history-test")
    monkeypatch.setenv("ALERT_STATE_TABLE", "alert-state-test")
    monkeypatch.delenv("ALERT_AUTO_PAUSE_SEC", raising=False)
    from alert_group_worker import lambda_handler as w
    w._get_ddb.cache_clear()
    w._policy.cache_clear()
    yield
    w._get_ddb.cache_clear()
    w._policy.cache_clear()


@pytest.fixture
def tables():
    from alert_group_worker import lambda_handler as w
    hist, state = FakeHistoryTable(), FakeStateTable()
    with patch.object(w, "_tables", return_value=(hist, state)):
        yield hist, state


def _member(series, key, *, state="ALARM", reason="", occurred_at="2026-09-02T10:15:30Z", gid=GROUP["group_id"]):
    return {"series_id": series, "event_key": key, "group_id": gid, "state": state,
            "suppression_reason": reason, "occurred_at": occurred_at, "severity": "SEV-3", "suppressed": False}


class TestClose:
    def test_closes_own_open_group(self, tables):
        from alert_group_worker import lambda_handler as w
        _, state = tables
        state.items["grp#cust-1#SEV-3"] = {"state_key": "grp#cust-1#SEV-3", "status": "open",
                                           "group_id": GROUP["group_id"], "version": 2}
        out = w.lambda_handler({"action": "close", "group": GROUP}, None)
        assert out["was_open"] is True and out["closed_at"].endswith("Z")
        it = state.items["grp#cust-1#SEV-3"]
        assert it["status"] == "closed" and it["closed_at"] == out["closed_at"] and it["version"] == 3

    def test_does_not_touch_a_newer_group(self, tables):
        from alert_group_worker import lambda_handler as w
        _, state = tables
        state.items["grp#cust-1#SEV-3"] = {"state_key": "grp#cust-1#SEV-3", "status": "open",
                                           "group_id": "g-newer", "version": 5}
        out = w.lambda_handler({"action": "close", "group": GROUP}, None)
        assert out["was_open"] is False
        assert state.items["grp#cust-1#SEV-3"]["status"] == "open"

    def test_already_closed_is_noop(self, tables):
        from alert_group_worker import lambda_handler as w
        _, state = tables
        state.items["grp#cust-1#SEV-3"] = {"state_key": "grp#cust-1#SEV-3", "status": "closed",
                                           "group_id": GROUP["group_id"], "version": 3}
        assert w.lambda_handler({"action": "close", "group": GROUP}, None)["was_open"] is False
        assert state.puts == 0

    def test_missing_group_item_is_noop(self, tables):
        from alert_group_worker import lambda_handler as w
        assert w.lambda_handler({"action": "close", "group": GROUP}, None)["was_open"] is False


class TestCollect:
    def test_counts_members_and_no_pause_without_deferred(self, tables, monkeypatch):
        from alert_group_worker import lambda_handler as w
        hist, _ = tables
        monkeypatch.setenv("ALERT_AUTO_PAUSE_SEC", '{"SEV-3": 300}')
        w._policy.cache_clear()
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a"))
        hist.put_item(Item=_member("1#i-2#CPU", "2026-09-02T10:15:31Z#b"))
        hist.put_item(Item=_member("1#i-9#CPU", "2026-09-02T10:15:32Z#c", gid="g-other"))
        out = w.lambda_handler({"action": "collect", "group": GROUP}, None)
        assert out == {"count": 2, "deferred": 0, "pause_sec": 0}

    def test_pause_when_deferred_and_policy_set(self, tables, monkeypatch):
        from alert_group_worker import lambda_handler as w
        hist, _ = tables
        monkeypatch.setenv("ALERT_AUTO_PAUSE_SEC", '{"SEV-3": 300}')
        w._policy.cache_clear()
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        out = w.lambda_handler({"action": "collect", "group": GROUP}, None)
        assert out == {"count": 1, "deferred": 1, "pause_sec": 300}

    def test_no_pause_when_policy_empty(self, tables):
        from alert_group_worker import lambda_handler as w
        hist, _ = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        assert w.lambda_handler({"action": "collect", "group": GROUP}, None)["pause_sec"] == 0


class TestFinalize:
    def test_notify_members_are_finalized_as_notify(self, tables):
        from alert_group_worker import lambda_handler as w
        hist, _ = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a"))
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:20:00Z#b", state="OK", reason="cleared"))
        out = w.lambda_handler({"action": "finalize", "group": GROUP}, None)
        assert out == {"count": 2, "deferred": 0, "notified": 2, "suppressed": 0}
        rows = hist.by_series("1#i-1#CPU")
        assert [r["final_action"] for r in rows] == ["notify", "notify"]
        assert rows[1]["final_reason"] == "cleared" and rows[0]["finalized_at"].endswith("Z")
        assert all(r["group_id"] == GROUP["group_id"] for r in rows)

    def test_deferred_resolved_during_pause_is_suppressed(self, tables):
        """auto-pause의 실제 이득 — 유예 중 스스로 풀린 알람은 보내지 않는다."""
        from alert_group_worker import lambda_handler as w
        hist, state = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        state.items["fp#1#i-1#CPU"] = {"state_key": "fp#1#i-1#CPU", "episode_open": False, "version": 2}
        out = w.lambda_handler({"action": "finalize", "group": GROUP}, None)
        assert out == {"count": 1, "deferred": 1, "notified": 0, "suppressed": 1}
        row = hist.by_series("1#i-1#CPU")[0]
        assert row["final_action"] == "suppress" and row["final_reason"] == "auto_pause"
        assert "last_notified_at" not in state.items["fp#1#i-1#CPU"]

    def test_deferred_still_firing_is_notified_and_marked(self, tables):
        from alert_group_worker import lambda_handler as w
        hist, state = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        state.items["fp#1#i-1#CPU"] = {"state_key": "fp#1#i-1#CPU", "episode_open": True,
                                       "episode_started_at": "2026-09-02T10:15:30Z",
                                       "episode_notified": False, "version": 2}
        out = w.lambda_handler({"action": "finalize", "group": GROUP}, None)
        assert out["notified"] == 1 and out["suppressed"] == 0
        row = hist.by_series("1#i-1#CPU")[0]
        assert row["final_action"] == "notify" and row["final_reason"] == "auto_pause_expired"
        fp = state.items["fp#1#i-1#CPU"]
        assert fp["last_notified_at"] == "2026-09-02T10:15:30Z" and fp["episode_notified"] is True
        assert fp["version"] == 3

    def test_deferred_whose_episode_was_replaced_is_suppressed(self, tables):
        """유예 중 해소됐다가 새 에피소드가 열렸다면, 이 이벤트의 에피소드는 끝난 것이다."""
        from alert_group_worker import lambda_handler as w
        hist, state = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        state.items["fp#1#i-1#CPU"] = {"state_key": "fp#1#i-1#CPU", "episode_open": True,
                                       "episode_started_at": "2026-09-02T10:19:00Z", "version": 4}
        out = w.lambda_handler({"action": "finalize", "group": GROUP}, None)
        assert out["suppressed"] == 1

    def test_missing_state_means_not_firing(self, tables):
        from alert_group_worker import lambda_handler as w
        hist, _ = tables
        hist.put_item(Item=_member("1#i-1#CPU", "2026-09-02T10:15:30Z#a", reason="auto_pause"))
        assert w.lambda_handler({"action": "finalize", "group": GROUP}, None)["suppressed"] == 1

    def test_empty_group_finalizes_cleanly(self, tables):
        from alert_group_worker import lambda_handler as w
        assert w.lambda_handler({"action": "finalize", "group": GROUP}, None)["count"] == 0


class TestInvocation:
    def test_unknown_action_raises(self, tables):
        from alert_group_worker import lambda_handler as w
        with pytest.raises(ValueError):
            w.lambda_handler({"action": "explode", "group": GROUP}, None)

    def test_missing_group_raises(self, tables):
        from alert_group_worker import lambda_handler as w
        with pytest.raises(ValueError):
            w.lambda_handler({"action": "close", "group": {"group_id": "g"}}, None)
