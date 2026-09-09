"""
인시던트 모델 (`common/incident.py`) — requirements R4, tasks 2.1

고정하는 것:
- 확인은 **한 번만** 기록된다. 두 번째 확인이 시각을 덮으면 MTTA가 거짓이 된다 (R4-3)
- 원인 알람이 **모두** 풀려야 해소된다. 하나라도 열려 있으면 아니다 (R4-4)
- 같은 지문이 여러 번 울려도 구성원은 한 번 — 사건의 크기는 "몇 번"이 아니라 "무엇이"
- 폭풍이 한 사건에 몰려도 항목이 무한히 자라지 않는다 (DynamoDB 400KB)
"""

from datetime import datetime, timedelta, timezone

import pytest

from common.incident import (
    MAX_MEMBERS,
    MAX_TIMELINE,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_TRIGGERED,
    acknowledge,
    from_item,
    incident_pointer,
    mark_renotified,
    merge_events,
    needs_renotify,
    new_incident,
    new_incident_id,
    resolve,
    should_resolve,
    summarize,
    to_dict,
    to_item,
)

T0 = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


def ev(series="111#i-1#CPU", alarm="[EC2] i-1 CPU > 80%"):
    return {"series_id": series, "alarm_name": alarm}


def opened(**over):
    inc = new_incident("cust-1", "SEV-2", now=T0, title="[EC2] i-1 CPU > 80%")
    inc.update(over)
    return inc


class TestCreation:
    def test_starts_triggered_with_a_timeline(self):
        inc = opened()
        assert inc["status"] == STATUS_TRIGGERED
        assert inc["triggered_at"] == "2026-09-09T10:00:00Z"
        assert inc["timeline"][0]["kind"] == "triggered"
        assert inc["members"] == [] and inc["event_count"] == 0

    def test_id_is_deterministic_per_axis_and_time(self):
        a = new_incident_id("cust-1", "SEV-2", "2026-09-09T10:00:00Z")
        b = new_incident_id("cust-1", "SEV-2", "2026-09-09T10:00:00Z")
        c = new_incident_id("cust-2", "SEV-2", "2026-09-09T10:00:00Z")
        assert a == b and a != c and a.startswith("inc-")

    def test_pointer_shares_the_group_axis(self):
        assert incident_pointer("cust-1", "SEV-2") == "inc#cust-1#SEV-2"

    def test_axis_is_the_group_key_verbatim(self):
        """미매핑 계정은 그룹처럼 계정별로 나뉜다 — `inc##SEV-x` 하나로 뭉치지 않는다 (review-phase2 M3)."""
        from common.incident import axis_of, pointer_for_axis
        inc = new_incident("", "SEV-2", now=T0, axis="111#SEV-2", account_id="111")
        assert inc["axis"] == "111#SEV-2" and inc["account_id"] == "111"
        assert pointer_for_axis(inc["axis"]) == "inc#111#SEV-2"
        assert axis_of(inc) == "111#SEV-2"
        assert new_incident_id("", "SEV-2", "2026-09-09T10:00:00Z", axis="111#SEV-2") == inc["incident_id"]

    def test_axis_defaults_to_customer_and_severity(self):
        from common.incident import axis_of
        inc = opened()
        assert inc["axis"] == "cust-1#SEV-2"
        legacy = {k: v for k, v in inc.items() if k != "axis"}
        assert axis_of(legacy) == "cust-1#SEV-2", "축을 저장하기 전의 행도 같은 포인터를 찾아야 한다"


class TestMerge:
    def test_adds_members_and_timeline(self):
        inc = merge_events(opened(), [ev(), ev("111#i-2#CPU", "[EC2] i-2")], now=T0)
        assert inc["members"] == ["111#i-1#CPU", "111#i-2#CPU"]
        assert inc["event_count"] == 2
        assert inc["timeline"][-1]["kind"] == "alarm"

    def test_same_fingerprint_does_not_duplicate_the_member(self):
        """사건의 크기는 '몇 번 울렸나'가 아니라 '무엇이 아픈가'다."""
        inc = merge_events(opened(), [ev(), ev(), ev()], now=T0)
        assert inc["members"] == ["111#i-1#CPU"]
        assert inc["event_count"] == 3, "소음의 양은 따로 남는다"

    def test_does_not_mutate_the_input(self):
        original = opened()
        merge_events(original, [ev()], now=T0)
        assert original["members"] == []

    def test_collects_account_and_resource_type_axes_for_channel_matching(self):
        """재알림이 계정·리소스 타입으로 좁힌 채널에도 가야 한다 (review-phase2 M4)."""
        from common.incident import match_fields
        inc = merge_events(opened(), [
            {**ev("111#i-1#CPU"), "account_id": "111", "resource_type": "EC2"},
            {**ev("222#db-1#Free"), "account_id": "222", "resource_type": "RDS"},
            {**ev("111#i-2#CPU"), "account_id": "111", "resource_type": "EC2"},
        ], now=T0)
        assert inc["account_ids"] == ["111", "222"] and inc["resource_types"] == ["EC2", "RDS"]
        view = match_fields(inc)
        assert view["account_id"] == ["111", "222"] and view["resource_type"] == ["EC2", "RDS"]
        assert view["severity"] == "SEV-2" and view["customer_id"] == "cust-1"

    def test_match_fields_fall_back_to_the_single_account_of_a_legacy_row(self):
        from common.incident import match_fields
        legacy = {**opened(), "account_id": "111"}
        assert match_fields(legacy)["account_id"] == ["111"]
        assert match_fields(opened())["account_id"] == []

    def test_events_without_a_fingerprint_are_ignored(self):
        inc = merge_events(opened(), [{"alarm_name": "x"}], now=T0)
        assert inc["members"] == [] and inc["event_count"] == 0

    def test_members_are_capped(self):
        many = [ev(f"111#i-{i}#CPU") for i in range(MAX_MEMBERS + 50)]
        inc = merge_events(opened(), many, now=T0)
        assert len(inc["members"]) == MAX_MEMBERS
        assert inc["event_count"] == MAX_MEMBERS + 50

    def test_timeline_is_capped_keeping_the_recent(self):
        inc = opened()
        for i in range(MAX_TIMELINE + 20):
            inc = merge_events(inc, [ev(f"111#i-{i}#CPU")], now=T0 + timedelta(seconds=i))
        assert len(inc["timeline"]) == MAX_TIMELINE
        assert inc["timeline"][-1]["kind"] == "alarm"


class TestAcknowledge:
    def test_records_who_and_when_and_computes_mtta(self):
        inc = acknowledge(opened(), by="oncall@mz.co.kr", now=T0 + timedelta(minutes=3))
        assert inc["status"] == STATUS_ACKNOWLEDGED
        assert inc["acknowledged_by"] == "oncall@mz.co.kr"
        assert inc["mtta_sec"] == 180
        assert inc["timeline"][-1]["kind"] == "acknowledged"

    def test_second_ack_does_not_overwrite_the_first(self):
        """두 번째 확인이 시각을 덮으면 MTTA가 거짓이 된다."""
        first = acknowledge(opened(), by="a@mz.co.kr", now=T0 + timedelta(minutes=3))
        second = acknowledge(first, by="b@mz.co.kr", now=T0 + timedelta(minutes=30))
        assert second["acknowledged_by"] == "a@mz.co.kr" and second["mtta_sec"] == 180

    def test_resolved_incident_cannot_be_acknowledged(self):
        done = resolve(opened(), now=T0 + timedelta(minutes=5))
        assert acknowledge(done, by="x", now=T0)["status"] == STATUS_RESOLVED


class TestResolve:
    def test_computes_mttr(self):
        inc = resolve(opened(), now=T0 + timedelta(minutes=12))
        assert inc["status"] == STATUS_RESOLVED and inc["mttr_sec"] == 720
        assert inc["timeline"][-1]["kind"] == "resolved"

    def test_second_resolve_keeps_the_first_time(self):
        first = resolve(opened(), now=T0 + timedelta(minutes=12))
        assert resolve(first, now=T0 + timedelta(hours=5))["mttr_sec"] == 720

    def test_resolving_after_ack_keeps_both_metrics(self):
        acked = acknowledge(opened(), by="a", now=T0 + timedelta(minutes=2))
        done = resolve(acked, now=T0 + timedelta(minutes=10))
        assert done["mtta_sec"] == 120 and done["mttr_sec"] == 600


class TestShouldResolve:
    def test_all_members_closed(self):
        inc = merge_events(opened(), [ev(), ev("111#i-2#CPU")], now=T0)
        assert should_resolve(inc, set()) is True

    def test_one_still_firing_blocks_resolution(self):
        inc = merge_events(opened(), [ev(), ev("111#i-2#CPU")], now=T0)
        assert should_resolve(inc, {"111#i-2#CPU"}) is False

    def test_empty_incident_is_not_resolved(self):
        """아직 아무것도 안 붙은 새 인시던트를 지우면 안 된다."""
        assert should_resolve(opened(), set()) is False


class TestRenotify:
    def test_acknowledged_but_unresolved_past_the_window(self):
        acked = acknowledge(opened(), by="a", now=T0)
        assert needs_renotify(acked, now=T0 + timedelta(minutes=61), after_sec=3600) is True
        assert needs_renotify(acked, now=T0 + timedelta(minutes=59), after_sec=3600) is False

    def test_triggered_incidents_are_not_renotified_here(self):
        """확인조차 안 된 건은 에스컬레이션(Phase 3)의 몫이다."""
        assert needs_renotify(opened(), now=T0 + timedelta(days=1), after_sec=3600) is False

    def test_resolved_is_never_renotified(self):
        done = resolve(acknowledge(opened(), by="a", now=T0), now=T0)
        assert needs_renotify(done, now=T0 + timedelta(days=1), after_sec=3600) is False

    def test_disabled_when_window_is_zero(self):
        acked = acknowledge(opened(), by="a", now=T0)
        assert needs_renotify(acked, now=T0 + timedelta(days=1), after_sec=0) is False

    def test_marking_resets_the_clock(self):
        acked = acknowledge(opened(), by="a", now=T0)
        again = mark_renotified(acked, now=T0 + timedelta(minutes=61))
        assert needs_renotify(again, now=T0 + timedelta(minutes=62), after_sec=3600) is False
        assert needs_renotify(again, now=T0 + timedelta(minutes=125), after_sec=3600) is True


class TestSerialisation:
    def test_round_trip_drops_only_ttl(self):
        inc = merge_events(opened(), [ev()], now=T0)
        item = to_item(inc, now=T0)
        assert "ttl" in item
        assert from_item(item) == inc

    def test_to_dict_normalises_the_version_too(self):
        """라이브에서 드러났다 — Decimal이 문자열 "1"로 나가 클라이언트가 숫자 비교를 못 했다."""
        from decimal import Decimal
        out = to_dict({**opened(), "version": Decimal("3")})
        assert out["version"] == 3 and isinstance(out["version"], int)

    def test_to_dict_normalises_decimals(self):
        from decimal import Decimal
        inc = {**opened(), "mtta_sec": Decimal("180"), "event_count": Decimal("4")}
        out = to_dict(inc)
        assert out["mtta_sec"] == 180 and out["event_count"] == 4
        assert isinstance(out["mtta_sec"], int)

    def test_open_flag(self):
        assert to_dict(opened())["is_open"] is True
        assert to_dict(resolve(opened(), now=T0))["is_open"] is False


class TestSummary:
    def test_averages_only_over_measured_incidents(self):
        a = resolve(acknowledge(opened(), by="x", now=T0 + timedelta(minutes=2)),
                    now=T0 + timedelta(minutes=10))
        b = acknowledge(opened(), by="y", now=T0 + timedelta(minutes=4))
        c = opened()
        s = summarize([a, b, c])
        assert s["total"] == 3
        assert s["acknowledged_count"] == 2 and s["resolved_count"] == 1
        assert s["mtta_sec_avg"] == 180.0 and s["mttr_sec_avg"] == 600.0
        assert s["by_status"][STATUS_TRIGGERED] == 1

    def test_empty_input_has_no_averages(self):
        s = summarize([])
        assert s["total"] == 0 and s["mtta_sec_avg"] is None and s["mttr_sec_avg"] is None
