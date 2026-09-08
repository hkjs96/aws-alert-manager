"""
알림 그룹 순수 부분 (common/alert_group.py) 테스트 — design.md D10

- 실행 이름: 결정적, Step Functions 제약(≤80자·허용 문자) 준수, 그룹 키/시각이 다르면 다름
- 실행 ARN: 상태 머신 ARN + 이름으로 결정
- 그룹 대상: NOTIFY/DEFER 상태 전이만 — 억제된 이벤트로 그룹을 열면 폭풍에 실행이 폭발한다
"""

import re

from common.alert_event import AlertEvent, CONFIG_CHANGE, STATE_CHANGE
from common.alert_group import (
    STATUS_OPEN,
    execution_arn,
    execution_input,
    execution_name,
    new_group,
    should_group,
)
from common.alert_suppression import DEFER, NOTIFY, SUPPRESS, Decision

SM = "arn:aws:states:us-east-1:111122223333:stateMachine:aws-monitoring-alert-group-dev"


def ev(**over):
    e = AlertEvent(event_type=STATE_CHANGE, customer_id="cust-1", severity="SEV-3",
                   state="ALARM", previous_state="OK", occurred_at="2026-09-02T10:15:30Z")
    for k, v in over.items():
        setattr(e, k, v)
    return e


class TestExecutionName:
    def test_deterministic_and_constrained(self):
        a = execution_name("cust-1#SEV-3", "2026-09-02T10:15:30Z")
        b = execution_name("cust-1#SEV-3", "2026-09-02T10:15:30Z")
        assert a == b
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", a)
        assert "#" not in a and ":" not in a and " " not in a

    def test_differs_by_key_and_time(self):
        base = execution_name("cust-1#SEV-3", "2026-09-02T10:15:30Z")
        assert execution_name("cust-2#SEV-3", "2026-09-02T10:15:30Z") != base
        assert execution_name("cust-1#SEV-3", "2026-09-02T10:15:31Z") != base

    def test_unicode_customer_id_is_safe(self):
        name = execution_name("고객사#SEV-1", "2026-09-02T10:15:30Z")
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)

    def test_empty_time_does_not_raise(self):
        assert execution_name("c#SEV-3", "").endswith("-0")


class TestExecutionArn:
    def test_derived_from_state_machine_arn(self):
        assert execution_arn(SM, "g-abc-1") == \
            "arn:aws:states:us-east-1:111122223333:execution:aws-monitoring-alert-group-dev:g-abc-1"


class TestShouldGroup:
    def test_notify_and_defer_state_changes_group(self):
        assert should_group(ev(), Decision(NOTIFY)) is True
        assert should_group(ev(), Decision(DEFER, "auto_pause", 300)) is True

    def test_clearing_notify_groups_too(self):
        """해소 알림도 그룹 통지에 실린다(Alertmanager send_resolved)."""
        assert should_group(ev(state="OK", previous_state="ALARM"), Decision(NOTIFY, "cleared")) is True

    def test_suppressed_never_groups(self):
        for reason in ("dedup", "flapping", "silence", "cleared", "not_actionable"):
            assert should_group(ev(), Decision(SUPPRESS, reason)) is False

    def test_config_change_never_groups(self):
        assert should_group(ev(event_type=CONFIG_CHANGE), Decision(NOTIFY)) is False


class TestGroupItem:
    def test_new_group_carries_execution_input(self):
        g = new_group("cust-1#SEV-3", ev(), opened_at="2026-09-02T10:15:30Z", group_wait_sec=30)
        assert g["status"] == STATUS_OPEN
        assert g["group_id"] == execution_name("cust-1#SEV-3", "2026-09-02T10:15:30Z")
        assert g["customer_id"] == "cust-1" and g["severity"] == "SEV-3"
        inp = execution_input(g)
        assert inp == {"group_id": g["group_id"], "group_key": "cust-1#SEV-3", "customer_id": "cust-1",
                       "severity": "SEV-3", "opened_at": "2026-09-02T10:15:30Z", "group_wait_sec": 30}

    def test_execution_input_tolerates_decimal_and_missing(self):
        from decimal import Decimal
        inp = execution_input({"group_id": "g", "group_wait_sec": Decimal("45")})
        assert inp["group_wait_sec"] == 45 and inp["group_key"] == ""


class TestGroupKeyFallback:
    """미등록 계정(customer_id 없음)은 account_id로 그룹을 나눈다 (review-personas F5)."""

    def test_registered_account_uses_customer_id(self):
        from common.alert_state import group_key
        from tests.test_alert_event import state_change_event
        from common.alert_event import from_eventbridge
        ev = from_eventbridge(state_change_event(account="111122223333"), customer_id="cust-1")
        ev.severity = "SEV-3"
        assert group_key(ev) == "cust-1#SEV-3"

    def test_unregistered_account_falls_back_to_account_id(self):
        from common.alert_state import group_key
        from tests.test_alert_event import state_change_event
        from common.alert_event import from_eventbridge
        a = from_eventbridge(state_change_event(account="111122223333"), customer_id="")
        b = from_eventbridge(state_change_event(account="999988887777"), customer_id="")
        a.severity = b.severity = "SEV-1"
        assert group_key(a) == "111122223333#SEV-1"
        assert group_key(b) == "999988887777#SEV-1"
        assert group_key(a) != group_key(b)     # 서로 다른 미등록 계정은 안 뭉친다
