"""
알림 정제 판정 (common/alert_suppression.py) 테스트

평가 순서가 곧 정책이므로 **순서를 뒤집는 조합**을 명시적으로 고정한다.
특히 SEV-1 면제(R3-8)는 다른 모든 억제보다 앞서야 한다 — 이게 뒤집히면
가장 중요한 알람이 조용히 사라진다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from common.alert_event import AlertEvent
from common.alert_suppression import (
    DEFER,
    NOTIFY,
    REASON_AUTO_PAUSE,
    REASON_CLEARED,
    REASON_DEDUP,
    REASON_FLAPPING,
    REASON_NOT_ACTIONABLE,
    REASON_SILENCE,
    SUPPRESS,
    Silence,
    SuppressionPolicy,
    decide,
    fingerprint,
    is_flapping,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def firing(severity="SEV-3", **over):
    ev = AlertEvent(
        event_type="state_change", state="ALARM", previous_state="OK",
        severity=severity, account_id="111", resource_id="i-1",
        metric_key="CPUUtilization", resource_type="EC2", customer_id="cust-1",
    )
    for k, v in over.items():
        setattr(ev, k, v)
    return ev


def clearing(**over):
    return firing(state="OK", previous_state="ALARM", **over)


def silence(minutes_from=-10, minutes_to=10, **kw):
    return Silence(
        starts_at=NOW + timedelta(minutes=minutes_from),
        ends_at=NOW + timedelta(minutes=minutes_to), **kw,
    )


class TestNonActionable:
    def test_config_change_never_notifies(self):
        """알람 생성/수정/삭제는 이력에는 남지만 사람을 깨우지 않는다."""
        ev = firing(event_type="config_change")
        d = decide(ev, policy=SuppressionPolicy(), now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_NOT_ACTIONABLE

    def test_insufficient_data_without_prior_alarm(self):
        ev = firing(state="INSUFFICIENT_DATA", previous_state="OK")
        assert decide(ev, policy=SuppressionPolicy(), now=NOW).action == SUPPRESS


class TestClearing:
    def test_clearing_notifies_only_if_we_notified_the_firing(self):
        pol = SuppressionPolicy()
        notified = decide(clearing(), policy=pol, already_notified=True, now=NOW)
        assert notified.action == NOTIFY and notified.reason == REASON_CLEARED

    def test_clearing_is_silent_when_firing_was_never_sent(self):
        """유예 중 스스로 풀린 알람 — auto-pause의 실제 이득이 발생하는 지점."""
        d = decide(clearing(), policy=SuppressionPolicy(), already_notified=False, now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_CLEARED

    def test_insufficient_data_from_alarm_counts_as_clearing(self):
        ev = firing(state="INSUFFICIENT_DATA", previous_state="ALARM")
        d = decide(ev, policy=SuppressionPolicy(), already_notified=True, now=NOW)
        assert d.action == NOTIFY and d.reason == REASON_CLEARED


class TestSeverityExemption:
    """SEV-1 면제는 다른 모든 억제보다 앞선다 (R3-8) — 순서가 뒤집히면 가장 중요한 알람이 사라진다."""

    def test_sev1_ignores_silence(self):
        pol = SuppressionPolicy(silences=(silence(),))
        assert decide(firing("SEV-1"), policy=pol, now=NOW).action == NOTIFY

    def test_sev1_ignores_flapping(self):
        d = decide(firing("SEV-1"), policy=SuppressionPolicy(), is_flapping=True, now=NOW)
        assert d.action == NOTIFY

    def test_sev1_ignores_dedup(self):
        d = decide(firing("SEV-1"), policy=SuppressionPolicy(),
                   last_notified_at=NOW - timedelta(minutes=1), now=NOW)
        assert d.action == NOTIFY

    def test_sev1_is_not_deferred(self):
        """유예도 곧 지연이다 — SEV-1은 즉시 보낸다."""
        pol = SuppressionPolicy(auto_pause_sec={"SEV-1": 300})
        assert decide(firing("SEV-1"), policy=pol, now=NOW).action == NOTIFY

    def test_non_exempt_severity_is_suppressed_normally(self):
        pol = SuppressionPolicy(silences=(silence(),))
        assert decide(firing("SEV-2"), policy=pol, now=NOW).action == SUPPRESS

    def test_exempt_list_is_configurable(self):
        pol = SuppressionPolicy(exempt_severities=("SEV-1", "SEV-2"), silences=(silence(),))
        assert decide(firing("SEV-2"), policy=pol, now=NOW).action == NOTIFY


class TestSilence:
    def test_active_window_suppresses(self):
        pol = SuppressionPolicy(silences=(silence(),))
        d = decide(firing(), policy=pol, now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_SILENCE

    def test_window_before_and_after(self):
        pol = SuppressionPolicy(silences=(silence(minutes_from=-60, minutes_to=-30),))
        assert decide(firing(), policy=pol, now=NOW).action == NOTIFY

    def test_end_is_exclusive(self):
        pol = SuppressionPolicy(silences=(silence(minutes_from=-10, minutes_to=0),))
        assert decide(firing(), policy=pol, now=NOW).action == NOTIFY

    def test_scoped_to_customer(self):
        pol = SuppressionPolicy(silences=(silence(customer_id="other"),))
        assert decide(firing(), policy=pol, now=NOW).action == NOTIFY
        pol2 = SuppressionPolicy(silences=(silence(customer_id="cust-1"),))
        assert decide(firing(), policy=pol2, now=NOW).action == SUPPRESS

    def test_scoped_to_resource_type(self):
        pol = SuppressionPolicy(silences=(silence(resource_type="RDS"),))
        assert decide(firing(), policy=pol, now=NOW).action == NOTIFY
        pol2 = SuppressionPolicy(silences=(silence(resource_type="EC2"),))
        assert decide(firing(), policy=pol2, now=NOW).action == SUPPRESS

    def test_any_matching_silence_applies(self):
        pol = SuppressionPolicy(silences=(silence(customer_id="other"), silence()))
        assert decide(firing(), policy=pol, now=NOW).action == SUPPRESS


class TestDedup:
    def test_within_repeat_interval_suppresses(self):
        pol = SuppressionPolicy(repeat_interval_sec=3600)
        d = decide(firing(), policy=pol, last_notified_at=NOW - timedelta(minutes=30), now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_DEDUP

    def test_after_repeat_interval_notifies_again(self):
        pol = SuppressionPolicy(repeat_interval_sec=3600)
        d = decide(firing(), policy=pol, last_notified_at=NOW - timedelta(hours=2), now=NOW)
        assert d.action == NOTIFY

    def test_boundary_is_exclusive_at_interval(self):
        pol = SuppressionPolicy(repeat_interval_sec=3600)
        exactly = decide(firing(), policy=pol, last_notified_at=NOW - timedelta(hours=1), now=NOW)
        assert exactly.action == NOTIFY

    def test_first_notification_is_not_deduped(self):
        assert decide(firing(), policy=SuppressionPolicy(), now=NOW).action == NOTIFY

    def test_clock_skew_future_timestamp_does_not_suppress(self):
        """미래 시각이 들어오면 억제하지 않는다 — 잘못된 상태로 알람을 영구히 막으면 안 된다."""
        pol = SuppressionPolicy(repeat_interval_sec=3600)
        d = decide(firing(), policy=pol, last_notified_at=NOW + timedelta(hours=1), now=NOW)
        assert d.action == NOTIFY


class TestAutoPause:
    def test_defers_when_configured(self):
        pol = SuppressionPolicy(auto_pause_sec={"SEV-3": 300})
        d = decide(firing("SEV-3"), policy=pol, now=NOW)
        assert d.action == DEFER and d.reason == REASON_AUTO_PAUSE and d.defer_seconds == 300

    def test_no_pause_configured_notifies_immediately(self):
        """실측 전 기본 상태 — 유예 설정이 없으면 즉시 보낸다."""
        assert decide(firing(), policy=SuppressionPolicy(), now=NOW).action == NOTIFY

    def test_per_severity_pause(self):
        pol = SuppressionPolicy(auto_pause_sec={"SEV-3": 120, "SEV-4": 600})
        assert decide(firing("SEV-3"), policy=pol, now=NOW).defer_seconds == 120
        assert decide(firing("SEV-4"), policy=pol, now=NOW).defer_seconds == 600
        # 표에 없는 severity는 유예하지 않는다
        assert decide(firing("SEV-5"), policy=pol, now=NOW).action == NOTIFY

    def test_silence_wins_over_pause(self):
        """억제될 이벤트를 유예로 붙잡아두면 타이머만 낭비한다."""
        pol = SuppressionPolicy(auto_pause_sec={"SEV-3": 300}, silences=(silence(),))
        assert decide(firing(), policy=pol, now=NOW).action == SUPPRESS

    def test_dedup_wins_over_pause(self):
        pol = SuppressionPolicy(auto_pause_sec={"SEV-3": 300}, repeat_interval_sec=3600)
        d = decide(firing(), policy=pol, last_notified_at=NOW - timedelta(minutes=10), now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_DEDUP


class TestFingerprint:
    def test_uses_series_id_not_alarm_name(self):
        """이름은 임계치가 바뀌면 달라진다 — 이름 기준이면 임계치 조정이 중복 판정을 초기화한다."""
        a = firing(alarm_name="[EC2] web CPUUtilization > 80% (TagName: i-1)")
        b = firing(alarm_name="[EC2] web CPUUtilization > 70% (TagName: i-1)")
        assert fingerprint(a) == fingerprint(b) == "111#i-1#CPUUtilization"

    def test_differs_by_metric(self):
        assert fingerprint(firing()) != fingerprint(firing(metric_key="mem_used_percent"))


class TestIsFlapping:
    def test_threshold(self):
        assert is_flapping(21, 7) is True       # 하루 3회
        assert is_flapping(20, 7) is False      # 하루 2.86회
        assert is_flapping(7, 7, threshold_per_day=1) is True

    def test_zero_window_is_not_flapping(self):
        assert is_flapping(100, 0) is False


class TestFlappingQuarantine:
    def test_suppresses(self):
        d = decide(firing(), policy=SuppressionPolicy(), is_flapping=True, now=NOW)
        assert d.action == SUPPRESS and d.reason == REASON_FLAPPING

    def test_silence_is_evaluated_before_flapping(self):
        pol = SuppressionPolicy(silences=(silence(),))
        d = decide(firing(), policy=pol, is_flapping=True, now=NOW)
        assert d.reason == REASON_SILENCE


class TestDecisionShape:
    def test_suppressed_property(self):
        assert decide(firing(), policy=SuppressionPolicy(), is_flapping=True, now=NOW).suppressed
        assert not decide(firing(), policy=SuppressionPolicy(), now=NOW).suppressed

    @pytest.mark.parametrize("action", [NOTIFY, SUPPRESS, DEFER])
    def test_actions_are_distinct(self, action):
        assert action in (NOTIFY, SUPPRESS, DEFER)
        assert len({NOTIFY, SUPPRESS, DEFER}) == 3
