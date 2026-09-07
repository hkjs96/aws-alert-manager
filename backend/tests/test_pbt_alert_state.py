"""
알림 상태 속성 테스트 (Hypothesis) — common/alert_state.py

임의의 발화/해소 열에 대해:
1. 판정·갱신 루프가 예외를 던지지 않고, recent_episodes가 정렬·중복 없음·상한 이내
2. **멱등** — 모든 이벤트를 즉시 한 번씩 더 넣어도(at-least-once 재현) 최종 상태·판정이 같다
3. 발화 NOTIFY 사이 간격은 repeat_interval 이상 — dedup이 새지 않는다
"""

from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from common.alert_event import AlertEvent, STATE_CHANGE
from common.alert_state import MAX_RECENT_EPISODES, apply_event, inputs_from_state
from common.alert_suppression import NOTIFY, SuppressionPolicy, decide

BASE = datetime(2026, 9, 2, tzinfo=timezone.utc)
POLICY = SuppressionPolicy()


def _event(kind: str, at: datetime, idx: int) -> AlertEvent:
    ts = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    firing = kind == "fire"
    return AlertEvent(
        event_type=STATE_CHANGE, event_id=f"{kind}-{idx}", occurred_at=ts,
        account_id="1", resource_id="i-1", metric_key="CPUUtilization", severity="SEV-3",
        state="ALARM" if firing else "OK", previous_state="OK" if firing else "ALARM",
    )


@st.composite
def event_sequences(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    gaps = draw(st.lists(st.integers(min_value=1, max_value=6 * 3600), min_size=n, max_size=n))
    kinds = draw(st.lists(st.sampled_from(["fire", "clear"]), min_size=n, max_size=n))
    t, events = BASE, []
    for i, (g, k) in enumerate(zip(gaps, kinds)):
        t += timedelta(seconds=g)
        events.append(_event(k, t, i))
    return events


def run(events):
    state, verdicts = None, []
    for ev in events:
        now = ev.occurred_dt
        inputs = inputs_from_state(state, ev, now=now, policy=POLICY)
        d = decide(ev, policy=POLICY, last_notified_at=inputs.last_notified_at,
                   is_flapping=inputs.is_flapping, already_notified=inputs.already_notified, now=now)
        state = apply_event(state, ev, d, now=now, policy=POLICY)
        eps = state.get("recent_episodes", [])
        assert eps == sorted(eps) and len(eps) == len(set(eps)) and len(eps) <= MAX_RECENT_EPISODES
        verdicts.append((ev.event_id, ev.state, d.action, d.reason))
    return state, verdicts


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(event_sequences())
def test_loop_never_raises_and_episodes_are_well_formed(events):
    run(events)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(event_sequences())
def test_at_least_once_delivery_does_not_change_outcome(events):
    """각 이벤트를 즉시 한 번 더 넣는다. 중복분은 상태를 바꾸지 않고, 원본 판정은 그대로다."""
    state_once, verdicts_once = run(events)
    doubled = [e for ev in events for e in (ev, ev)]
    state_twice, verdicts_twice = run(doubled)
    assert state_twice == state_once
    assert verdicts_twice[::2] == verdicts_once          # 원본 판정은 동일
    for _, _, action, _ in verdicts_twice[1::2]:          # 중복분은 절대 NOTIFY가 아니다
        assert action != NOTIFY


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(event_sequences())
def test_firing_notifies_are_at_least_repeat_interval_apart(events):
    _, verdicts = run(events)
    by_id = {ev.event_id: ev for ev in events}
    notified = [by_id[eid].occurred_dt for eid, state, action, _ in verdicts
                if state == "ALARM" and action == NOTIFY]
    for a, b in zip(notified, notified[1:]):
        assert (b - a).total_seconds() >= POLICY.repeat_interval_sec
