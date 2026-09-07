"""
알림 상태 (common/alert_state.py) 테스트 — design.md D9

이 모듈이 틀리면 dedup·flapping·해소 알림이 전부 틀린다. 고정하는 것:
- 상태 → 판정 재료 변환 (없음 = 첫 발화, 격리, 창 안 에피소드 수에 현재 발화 포함)
- 이벤트 → 상태 전이 표 (발화/해소/설정 변경 × 판정)
- **멱등** — 같은 이벤트 두 번 = 한 번 (EventBridge at-least-once)
- 저장 필드(version/ttl/state_key)는 상태 비교에서 제외
- 시나리오: 25번 토글 → 발화 NOTIFY 1건 (review-2026-09-07 B1의 받아들임 기준)
"""

from datetime import datetime, timedelta, timezone

from common.alert_event import AlertEvent, STATE_CHANGE, CONFIG_CHANGE
from common.alert_state import (
    MAX_RECENT_EPISODES,
    StateInputs,
    apply_event,
    fp_key,
    group_key,
    grp_key,
    inputs_from_state,
    state_item,
    unchanged,
)
from common.alert_suppression import (
    DEFER, NOTIFY, SUPPRESS, REASON_CLEARED, REASON_DEDUP, REASON_FLAPPING,
    Decision, SuppressionPolicy, decide,
)

T0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
POLICY = SuppressionPolicy()      # repeat 4h, flapping 3/일(창 1일), 격리 1h


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def firing(at: datetime, **over) -> AlertEvent:
    ev = AlertEvent(event_type=STATE_CHANGE, event_id=f"f-{iso(at)}", occurred_at=iso(at),
                    account_id="1", resource_id="i-1", metric_key="CPUUtilization",
                    severity="SEV-3", state="ALARM", previous_state="OK", customer_id="c1")
    for k, v in over.items():
        setattr(ev, k, v)
    return ev


def clearing(at: datetime) -> AlertEvent:
    ev = firing(at)
    ev.state, ev.previous_state, ev.event_id = "OK", "ALARM", f"c-{iso(at)}"
    return ev


class TestKeys:
    def test_fp_and_grp_prefixes(self):
        assert fp_key("1#i-1#CPU") == "fp#1#i-1#CPU"
        assert grp_key("c1#SEV-3") == "grp#c1#SEV-3"

    def test_group_key_is_customer_and_severity(self):
        assert group_key(firing(T0)) == "c1#SEV-3"


class TestInputsFromState:
    def test_no_state_means_first_occurrence(self):
        assert inputs_from_state(None, firing(T0), now=T0, policy=POLICY) == StateInputs()

    def test_last_notified_is_parsed(self):
        s = {"last_notified_at": "2026-09-02T09:00:00Z"}
        assert inputs_from_state(s, firing(T0), now=T0, policy=POLICY).last_notified_at \
            == T0 - timedelta(hours=1)

    def test_already_notified_requires_open_and_notified(self):
        ev = clearing(T0)
        assert inputs_from_state({"episode_open": True, "episode_notified": True}, ev,
                                 now=T0, policy=POLICY).already_notified is True
        assert inputs_from_state({"episode_open": False, "episode_notified": True}, ev,
                                 now=T0, policy=POLICY).already_notified is False
        assert inputs_from_state({"episode_open": True, "episode_notified": False}, ev,
                                 now=T0, policy=POLICY).already_notified is False

    def test_quarantine_makes_flapping_until_expiry(self):
        s = {"quarantined_until": iso(T0 + timedelta(minutes=30))}
        assert inputs_from_state(s, firing(T0), now=T0, policy=POLICY).is_flapping is True
        later = T0 + timedelta(minutes=31)
        assert inputs_from_state(s, firing(later), now=later, policy=POLICY).is_flapping is False

    def test_current_firing_counts_toward_flapping(self):
        """세 번째 발화가 세 번째로 세어져야 한다 — 빼면 격리가 한 박자 늦다."""
        s = {"recent_episodes": [iso(T0 - timedelta(hours=2)), iso(T0 - timedelta(hours=1))]}
        assert inputs_from_state(s, firing(T0), now=T0, policy=POLICY).is_flapping is True

    def test_episodes_outside_window_do_not_count(self):
        s = {"recent_episodes": [iso(T0 - timedelta(days=2)), iso(T0 - timedelta(days=3))]}
        assert inputs_from_state(s, firing(T0), now=T0, policy=POLICY).is_flapping is False

    def test_clearing_never_evaluates_flapping_count(self):
        s = {"recent_episodes": [iso(T0 - timedelta(hours=h)) for h in (1, 2, 3, 4)]}
        assert inputs_from_state(s, clearing(T0), now=T0, policy=POLICY).is_flapping is False

    def test_garbage_timestamps_are_ignored(self):
        s = {"last_notified_at": "nonsense", "quarantined_until": 42,
             "recent_episodes": ["bad", None, iso(T0)]}
        inputs = inputs_from_state(s, firing(T0), now=T0, policy=POLICY)
        assert inputs.last_notified_at is None and inputs.is_flapping is False


class TestApplyEvent:
    def test_first_firing_opens_episode(self):
        new = apply_event(None, firing(T0), Decision(NOTIFY), now=T0, policy=POLICY)
        assert new["episode_open"] is True
        assert new["episode_started_at"] == iso(T0)
        assert new["recent_episodes"] == [iso(T0)]

    def test_notify_records_last_notified_and_marks_episode(self):
        new = apply_event(None, firing(T0), Decision(NOTIFY), now=T0, policy=POLICY)
        assert new["last_notified_at"] == iso(T0) and new["episode_notified"] is True

    def test_dedup_leaves_last_notified_alone(self):
        s = {"last_notified_at": iso(T0 - timedelta(hours=1)), "episode_open": False}
        new = apply_event(s, firing(T0), Decision(SUPPRESS, REASON_DEDUP), now=T0, policy=POLICY)
        assert new["last_notified_at"] == iso(T0 - timedelta(hours=1))
        assert new["episode_open"] is True and new["episode_notified"] is False

    def test_defer_opens_episode_without_notified_flag(self):
        new = apply_event(None, firing(T0), Decision(DEFER, "auto_pause", 300),
                          now=T0, policy=POLICY)
        assert new["episode_open"] is True and new["episode_notified"] is False
        assert "last_notified_at" not in new

    def test_clearing_closes_episode(self):
        s = {"episode_open": True, "episode_notified": True, "last_notified_at": iso(T0)}
        new = apply_event(s, clearing(T0 + timedelta(minutes=5)),
                          Decision(NOTIFY, REASON_CLEARED), now=T0, policy=POLICY)
        assert new["episode_open"] is False
        assert new["last_notified_at"] == iso(T0)      # 해소 알림은 발화 dedup 창을 건드리지 않는다

    def test_config_change_does_not_touch_state(self):
        s = {"episode_open": True, "recent_episodes": [iso(T0)]}
        ev = firing(T0, event_type=CONFIG_CHANGE, operation="update")
        assert apply_event(s, ev, Decision(SUPPRESS, "not_actionable"), now=T0, policy=POLICY) == s

    def test_storage_fields_are_stripped(self):
        s = {"state_key": "fp#x", "version": 7, "ttl": 1, "episode_open": True}
        new = apply_event(s, clearing(T0), Decision(SUPPRESS, REASON_CLEARED), now=T0, policy=POLICY)
        assert not ({"state_key", "version", "ttl"} & new.keys())

    def test_recent_episodes_sorted_windowed_capped(self):
        old = [iso(T0 - timedelta(days=3))]                       # 창 밖 → 버림
        recent = [iso(T0 - timedelta(minutes=m)) for m in range(60, 0, -1)]   # 60개, 역순
        s = {"recent_episodes": old + recent}
        new = apply_event(s, firing(T0), Decision(NOTIFY), now=T0, policy=POLICY)
        eps = new["recent_episodes"]
        assert eps == sorted(eps) and len(eps) == MAX_RECENT_EPISODES
        assert eps[-1] == iso(T0) and old[0] not in eps

    def test_newly_detected_flapping_starts_quarantine(self):
        new = apply_event(None, firing(T0), Decision(SUPPRESS, REASON_FLAPPING), now=T0, policy=POLICY)
        assert new["quarantined_until"] == iso(T0 + timedelta(seconds=POLICY.flapping_quarantine_sec))

    def test_existing_quarantine_is_not_extended(self):
        s = {"quarantined_until": iso(T0 + timedelta(minutes=10))}
        new = apply_event(s, firing(T0), Decision(SUPPRESS, REASON_FLAPPING), now=T0, policy=POLICY)
        assert new["quarantined_until"] == iso(T0 + timedelta(minutes=10))

    def test_expired_quarantine_is_restarted(self):
        s = {"quarantined_until": iso(T0 - timedelta(minutes=1))}
        new = apply_event(s, firing(T0), Decision(SUPPRESS, REASON_FLAPPING), now=T0, policy=POLICY)
        assert new["quarantined_until"] == iso(T0 + timedelta(seconds=POLICY.flapping_quarantine_sec))

    def test_input_state_is_not_mutated(self):
        s = {"recent_episodes": [], "episode_open": False}
        snapshot = {k: list(v) if isinstance(v, list) else v for k, v in s.items()}
        apply_event(s, firing(T0), Decision(NOTIFY), now=T0, policy=POLICY)
        assert s == snapshot


class TestIdempotency:
    """EventBridge는 at-least-once — 같은 이벤트가 두 번 와도 상태가 같아야 한다."""

    def _step(self, state, ev):
        inputs = inputs_from_state(state, ev, now=ev.occurred_dt, policy=POLICY)
        d = decide(ev, policy=POLICY, last_notified_at=inputs.last_notified_at,
                   is_flapping=inputs.is_flapping, already_notified=inputs.already_notified,
                   now=ev.occurred_dt)
        return apply_event(state, ev, d, now=ev.occurred_dt, policy=POLICY), d

    def test_duplicate_firing_is_dedup_and_state_unchanged(self):
        s1, d1 = self._step(None, firing(T0))
        s2, d2 = self._step(s1, firing(T0))
        assert d1.action == NOTIFY and d2.reason == REASON_DEDUP
        assert s2 == s1

    def test_duplicate_clearing_notifies_once(self):
        s1, _ = self._step(None, firing(T0))
        s2, d2 = self._step(s1, clearing(T0 + timedelta(minutes=1)))
        s3, d3 = self._step(s2, clearing(T0 + timedelta(minutes=1)))
        assert d2.action == NOTIFY and d3.action == SUPPRESS
        assert s3 == s2

    def test_duplicate_flapping_firing_keeps_quarantine(self):
        s = {"recent_episodes": [iso(T0 - timedelta(hours=2)), iso(T0 - timedelta(hours=1))]}
        s1, d1 = self._step(s, firing(T0))
        s2, d2 = self._step(s1, firing(T0))
        assert d1.reason == REASON_FLAPPING and d2.reason == REASON_FLAPPING
        assert s2 == s1


class TestUnchangedAndItem:
    def test_unchanged_ignores_storage_fields(self):
        assert unchanged({"state_key": "k", "version": 2, "ttl": 9, "episode_open": True},
                         {"episode_open": True})

    def test_state_item_sets_key_version_ttl(self):
        item = state_item("fp#x", {"episode_open": True, "version": 99}, now=T0, version=3)
        assert item["state_key"] == "fp#x" and item["version"] == 3
        assert item["ttl"] == int((T0 + timedelta(days=30)).timestamp())
        assert item["episode_open"] is True


class TestScenarioB1:
    """review-2026-09-07 B1의 받아들임 기준: 25번 토글 → 발화 NOTIFY 1건.

    이력 스캔(Limit=20)으로는 ~10번마다 NOTIFY가 새어 나왔다. 상태 테이블이면 새지 않는다.
    """

    def test_25_toggles_notify_once(self):
        state, verdicts = None, []
        for i in range(25):
            for ev in (firing(T0 + timedelta(minutes=4 * i)),
                       clearing(T0 + timedelta(minutes=4 * i + 2))):
                inputs = inputs_from_state(state, ev, now=ev.occurred_dt, policy=POLICY)
                d = decide(ev, policy=POLICY, last_notified_at=inputs.last_notified_at,
                           is_flapping=inputs.is_flapping, already_notified=inputs.already_notified,
                           now=ev.occurred_dt)
                state = apply_event(state, ev, d, now=ev.occurred_dt, policy=POLICY)
                verdicts.append((ev.state, d.action, d.reason))

        fired = [v for v in verdicts if v[0] == "ALARM"]
        cleared = [v for v in verdicts if v[0] == "OK"]
        assert sum(1 for v in fired if v[1] == NOTIFY) == 1
        assert sum(1 for v in fired if v[2] == REASON_DEDUP) == 1          # 2번째
        assert sum(1 for v in fired if v[2] == REASON_FLAPPING) == 23      # 3번째부터 격리
        assert sum(1 for v in cleared if v[1] == NOTIFY) == 1               # 알린 에피소드의 해소만
