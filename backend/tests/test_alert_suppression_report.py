"""
억제율 리포트 (scripts/alert_suppression_report.py) 순수 로직 테스트 — tasks 1.5

이 숫자가 Phase 2 진입 판단과 auto-pause 값 결정의 근거가 된다. 고정하는 것:
- 최종값 규칙: final_action > suppressed > auto_pause(pending) > notify — 그룹 워커의 write-back이 이긴다
- 전이 분류: 발화 / 해소 / 기타 / 설정
- 억제율 분모는 확정된 발화(pending 제외)
- 빈 입력·0 나눗셈 방어, 렌더 안정성
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from alert_suppression_report import (  # noqa: E402
    NOTIFY, PENDING, SUPPRESS, aggregate, effective, kind, render,
)

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 8, tzinfo=timezone.utc)


def ev(series="1#i-1#CPU", state="ALARM", prev="OK", *, suppressed=False, reason="",
       final=None, final_reason="", sev="SEV-3", cust="c1", gid="", **extra):
    it = {"series_id": series, "event_key": f"{T0:%Y-%m-%dT%H:%M:%SZ}#x", "event_type": "state_change",
          "state": state, "previous_state": prev, "suppressed": suppressed, "severity": sev,
          "customer_id": cust, "alarm_name": f"[EC2] {series}"}
    if reason:
        it["suppression_reason"] = reason
    if final:
        it["final_action"], it["final_reason"] = final, final_reason
    if gid:
        it["group_id"] = gid
    it.update(extra)
    return it


class TestEffective:
    def test_final_action_wins_over_ingest_verdict(self):
        """그룹 워커가 확정한 값이 적재 시 판정보다 우선 — DEFER의 유예 결과가 여기서 반영된다."""
        assert effective(ev(reason="auto_pause", final="suppress", final_reason="auto_pause")) == (SUPPRESS, "auto_pause")
        assert effective(ev(reason="auto_pause", final="notify", final_reason="auto_pause_expired")) == (NOTIFY, "auto_pause_expired")

    def test_suppressed_at_ingest(self):
        assert effective(ev(suppressed=True, reason="dedup")) == (SUPPRESS, "dedup")

    def test_deferred_without_final_is_pending(self):
        assert effective(ev(reason="auto_pause")) == (PENDING, "auto_pause")

    def test_plain_notify(self):
        assert effective(ev()) == (NOTIFY, "")
        assert effective(ev(state="OK", prev="ALARM", reason="cleared")) == (NOTIFY, "cleared")


class TestKind:
    def test_classification(self):
        assert kind(ev()) == "firing"
        assert kind(ev(state="OK", prev="ALARM")) == "clearing"
        assert kind(ev(state="INSUFFICIENT_DATA", prev="ALARM")) == "clearing"
        assert kind(ev(state="OK", prev="INSUFFICIENT_DATA")) == "other"
        assert kind(ev(event_type="config_change")) == "config"


class TestAggregate:
    def _items(self):
        return [
            ev("1#i-1#CPU"),                                              # notify
            ev("1#i-1#CPU", suppressed=True, reason="dedup"),             # suppress
            ev("1#i-1#CPU", suppressed=True, reason="flapping"),
            ev("1#i-2#CPU", sev="SEV-1", gid="g-1", final="notify"),       # grouped, finalized
            ev("1#i-3#CPU", reason="auto_pause", gid="g-1", final="suppress", final_reason="auto_pause"),
            ev("1#i-4#CPU", reason="auto_pause"),                         # pending
            ev("1#i-1#CPU", state="OK", prev="ALARM", reason="cleared", gid="g-1", final="notify", final_reason="cleared"),
            ev("1#i-5#CPU", state="OK", prev="ALARM", suppressed=True, reason="cleared"),
            ev("1#i-6#CPU", state="OK", prev="INSUFFICIENT_DATA", suppressed=True, reason="not_actionable"),
            ev("1#i-7#CPU", event_type="config_change", suppressed=True, reason="not_actionable", parse_error="unmanaged alarm format"),
        ]

    def test_counts_and_rate(self):
        a = aggregate(self._items())
        assert a["events"] == 10
        assert a["kinds"] == {"firing": 6, "clearing": 2, "other": 1, "config": 1}
        assert a["firing"] == {NOTIFY: 2, SUPPRESS: 3, PENDING: 1}
        assert a["firing_decided"] == 5
        assert abs(a["suppression_rate"] - 3 / 5) < 1e-9          # pending은 분모에서 제외
        assert a["firing_reason"] == {"dedup": 1, "flapping": 1, "auto_pause": 1}

    def test_clearing_and_other_are_not_firing(self):
        a = aggregate(self._items())
        assert a["clearing"] == {NOTIFY: 1, SUPPRESS: 1}

    def test_by_severity_and_customer(self):
        a = aggregate(self._items())
        assert a["by_severity"]["SEV-1"] == {NOTIFY: 1}
        assert a["by_severity"]["SEV-3"] == {NOTIFY: 1, SUPPRESS: 3, PENDING: 1}
        assert a["by_customer"]["c1"][SUPPRESS] == 3

    def test_top_series_sorted_by_firings(self):
        a = aggregate(self._items())
        top = a["top_series"][0]
        assert top["series_id"] == "1#i-1#CPU" and top["notify"] == 1 and top["suppress"] == 2
        assert top["top_reason"] in ("dedup", "flapping")

    def test_groups(self):
        a = aggregate(self._items())
        g = a["groups"]
        assert g["count"] == 1 and g["events"] == 3 and g["max_size"] == 3
        assert g["final"] == {"notify": 1, "notify/cleared": 1, "suppress/auto_pause": 1}
        assert g["auto_pause_suppressed"] == 1 and g["auto_pause_expired"] == 0

    def test_quality(self):
        a = aggregate(self._items())
        assert a["quality"] == {"unmanaged": 1, "pending": 1}

    def test_grouped_but_not_finalized_is_flagged(self):
        a = aggregate([ev(gid="g-9")])
        assert a["quality"]["grouped_not_finalized"] == 1

    def test_empty_input_does_not_divide_by_zero(self):
        a = aggregate([])
        assert a["suppression_rate"] == 0.0 and a["groups"]["avg_size"] == 0.0


class TestRender:
    def test_full_report(self):
        out = render(aggregate(TestAggregate()._items()), start=T0, end=T1, customers=["c1"])
        assert "억제율 **60.0%**" in out
        assert "`dedup`" in out and "`flapping`" in out
        assert "auto-pause 이득" in out
        assert "미관리 알람" in out and "1건" in out
        assert "하한" in out                                           # silence 미배선 주의

    def test_empty_window_warns(self):
        out = render(aggregate([]), start=T0, end=T1, customers=[])
        assert "판정이 확정된 발화가 없다" in out

    def test_pending_only_window_warns(self):
        out = render(aggregate([ev(reason="auto_pause")]), start=T0, end=T1, customers=[])
        assert "판정이 확정된 발화가 없다" in out
