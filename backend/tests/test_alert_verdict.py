"""
판정 최종값과 사람 설명 (`common/alert_verdict.py`) — review-personas F7

화면과 억제율 리포트가 **같은 구현**을 쓴다. 여기서 고정하는 것:
- 최종값 규칙: final_action > suppressed > auto_pause(pending) > notify
- 모르는 사유를 조용히 "정상"으로 바꾸지 않는다 (새 억제 규칙이 생겨도 고객이 이유를 본다)
- 죽은 실행 청소(`swept:*`) 표식이 원래 사유와 함께 읽힌다
"""

import pytest

from common.alert_verdict import (
    NOTIFY,
    PENDING,
    SUPPRESS,
    describe,
    effective,
    kind,
    verdict,
)


def ev(**over):
    item = {"event_type": "state_change", "state": "ALARM", "previous_state": "OK"}
    item.update(over)
    return item


class TestEffective:
    def test_plain_notify(self):
        assert effective(ev()) == (NOTIFY, "")

    def test_suppressed_at_ingest(self):
        assert effective(ev(suppressed=True, suppression_reason="dedup")) == (SUPPRESS, "dedup")

    def test_auto_pause_is_pending_until_the_group_decides(self):
        assert effective(ev(suppression_reason="auto_pause")) == (PENDING, "auto_pause")

    def test_final_action_beats_ingest_time_verdict(self):
        """그룹 워커의 write-back이 이긴다 — 유예 중 스스로 풀린 알람이 여기로 온다."""
        item = ev(suppressed=True, suppression_reason="auto_pause",
                  final_action="suppress", final_reason="auto_pause")
        assert effective(item) == (SUPPRESS, "auto_pause")

    def test_final_notify_overrides_suppressed_flag(self):
        item = ev(suppressed=True, suppression_reason="auto_pause",
                  final_action="notify", final_reason="auto_pause_expired")
        assert effective(item) == (NOTIFY, "auto_pause_expired")


class TestKind:
    def test_firing(self):
        assert kind(ev()) == "firing"

    def test_clearing(self):
        assert kind(ev(state="OK", previous_state="ALARM")) == "clearing"

    def test_insufficient_data_from_alarm_is_clearing(self):
        assert kind(ev(state="INSUFFICIENT_DATA", previous_state="ALARM")) == "clearing"

    def test_config_event(self):
        assert kind(ev(event_type="config_change")) == "config"

    def test_other(self):
        assert kind(ev(state="OK", previous_state="OK")) == "other"


class TestDescribe:
    @pytest.mark.parametrize("reason,label", [
        ("dedup", "중복 병합"),
        ("flapping", "진동 격리"),
        ("silence", "정비창"),
        ("cleared", "해소"),
        ("not_actionable", "대상 아님"),
        ("auto_pause", "자동 유예"),
        ("auto_pause_expired", "유예 후 발송"),
        ("state_contention", "상태 경합"),
        ("", "정상 발송"),
    ])
    def test_every_reason_the_pipeline_emits_has_words(self, reason, label):
        out = describe(SUPPRESS, reason)
        assert out["reason_label"] == label
        assert out["explanation"], "설명이 비면 화면에서 사유를 알 수 없다"

    def test_action_labels(self):
        assert describe(NOTIFY, "")["action_label"] == "발송"
        assert describe(SUPPRESS, "dedup")["action_label"] == "억제"
        assert describe(PENDING, "auto_pause")["action_label"] == "유예 중"

    def test_unknown_reason_is_shown_not_swallowed(self):
        """새 억제 규칙이 생겨도 고객이 토큰이라도 본다 — 조용히 '정상'이 되면 안 된다."""
        out = describe(SUPPRESS, "brand_new_rule")
        assert out["reason_label"] == "brand_new_rule"
        assert "해석하지 못했" in out["explanation"]

    def test_swept_suffix_is_explained_with_the_original_reason(self):
        out = describe(NOTIFY, "auto_pause_expired;swept:failed")
        assert out["reason_label"] == "유예 후 발송"
        assert "실행이 실패" in out["explanation"]

    def test_swept_alone(self):
        out = describe(NOTIFY, "swept:aborted")
        assert out["reason_label"] == "실행 실패 후 발송"

    def test_raw_values_are_preserved_for_filtering(self):
        out = describe(SUPPRESS, "dedup")
        assert (out["action"], out["reason"]) == (SUPPRESS, "dedup")


class TestVerdict:
    def test_combines_effective_and_describe(self):
        out = verdict(ev(suppressed=True, suppression_reason="silence"))
        assert out["action"] == SUPPRESS
        assert out["reason_label"] == "정비창"


class TestReportUsesTheSameRules:
    """억제율 리포트와 조회 API의 숫자가 갈리면 어느 쪽이 맞는지 알 수 없다."""

    def test_script_imports_the_shared_implementation(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import alert_suppression_report as report
        import common.alert_verdict as shared
        assert report.effective is shared.effective
        assert report.kind is shared.kind
        assert (report.NOTIFY, report.SUPPRESS, report.PENDING) == (NOTIFY, SUPPRESS, PENDING)
