"""
알람 이력 분석 (scripts/analyze_alarm_history.py) 순수 로직 테스트

이 스크립트가 내놓는 "N분 유예 시 억제율"이 Phase 1의 auto-pause 기본값을 정한다.
숫자가 틀리면 잘못된 값으로 설계가 굳으므로 경계 조건을 고정한다.

- 에피소드 묶기: ALARM→OK 짝, 연속 재진입, 미해소, 창 시작 시 이미 ALARM
- 억제율: 경계값 포함 여부, 미해소는 억제 안 됨
- 집중도/백분위: 빈 입력 방어
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 분석 스크립트는 Lambda 번들에 넣지 않으려고 scripts/에 둔다 — 테스트에서만 경로를 얹는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from analyze_alarm_history import (  # noqa: E402
    analyze,
    build_episodes,
    concentration,
    humanize,
    parse_state,
    percentile,
    recommend_pause,
    render,
    suppression_rate,
)
from collections import Counter  # noqa: E402

T0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
END = T0 + timedelta(days=1)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


class TestParseState:
    def test_extracts_new_state(self):
        assert parse_state('{"newState":{"stateValue":"ALARM"}}') == "ALARM"

    def test_malformed_returns_empty(self):
        assert parse_state("not json") == ""
        assert parse_state("") == ""
        assert parse_state("[]") == ""
        assert parse_state('{"newState":{}}') == ""


class TestBuildEpisodes:
    def test_pairs_alarm_to_ok(self):
        eps = build_episodes([(at(0), "ALARM"), (at(4), "OK")], END)
        assert len(eps) == 1
        assert eps[0]["duration_sec"] == 240 and eps[0]["resolved"] is True

    def test_unsorted_input_is_sorted(self):
        eps = build_episodes([(at(4), "OK"), (at(0), "ALARM")], END)
        assert len(eps) == 1 and eps[0]["duration_sec"] == 240

    def test_repeated_alarm_counts_first_entry_only(self):
        # 같은 발화 중 ALARM이 여러 번 기록돼도 에피소드는 하나이며 시작은 첫 진입
        eps = build_episodes(
            [(at(0), "ALARM"), (at(2), "ALARM"), (at(10), "OK")], END,
        )
        assert len(eps) == 1 and eps[0]["duration_sec"] == 600

    def test_multiple_episodes(self):
        eps = build_episodes(
            [(at(0), "ALARM"), (at(3), "OK"), (at(60), "ALARM"), (at(75), "OK")], END,
        )
        assert [e["duration_sec"] for e in eps] == [180, 900]

    def test_insufficient_data_also_clears(self):
        eps = build_episodes([(at(0), "ALARM"), (at(5), "INSUFFICIENT_DATA")], END)
        assert len(eps) == 1 and eps[0]["resolved"] is True

    def test_unresolved_uses_window_end_as_lower_bound(self):
        eps = build_episodes([(at(0), "ALARM")], END)
        assert len(eps) == 1
        assert eps[0]["resolved"] is False
        assert eps[0]["duration_sec"] == 86400  # 창 끝까지
        assert eps[0]["end"] is None

    def test_alarm_already_active_at_window_start_is_excluded(self):
        # 진입 시각을 모르는 에피소드를 포함하면 지속시간이 짧게 잡혀 유예 효과가 과대평가된다
        eps = build_episodes([(at(5), "OK"), (at(60), "ALARM"), (at(70), "OK")], END)
        assert [e["duration_sec"] for e in eps] == [600]

    def test_no_transitions(self):
        assert build_episodes([], END) == []

    def test_only_ok_transitions(self):
        assert build_episodes([(at(1), "OK"), (at(2), "OK")], END) == []


class TestSuppressionRate:
    def _eps(self, *durations_sec, resolved=True):
        return [{"duration_sec": d, "resolved": resolved} for d in durations_sec]

    def test_counts_episodes_within_grace(self):
        eps = self._eps(60, 120, 600)          # 1분, 2분, 10분
        assert suppression_rate(eps, 5) == (2, 3)

    def test_boundary_is_inclusive(self):
        # 정확히 유예 시간에 해소된 건은 억제된 것으로 센다
        assert suppression_rate(self._eps(300), 5) == (1, 1)
        assert suppression_rate(self._eps(301), 5) == (0, 1)

    def test_unresolved_is_never_suppressed(self):
        # 미해소는 duration이 창 끝까지의 하한이므로 유예를 넘긴 것
        eps = self._eps(60, resolved=False)
        assert suppression_rate(eps, 5) == (0, 1)

    def test_mixed(self):
        eps = self._eps(60, 120) + self._eps(30, resolved=False)
        assert suppression_rate(eps, 5) == (2, 3)

    def test_empty(self):
        assert suppression_rate([], 5) == (0, 0)


class TestPercentile:
    def test_basic(self):
        assert percentile([1, 2, 3, 4, 5], 50) == 3
        assert percentile([1, 2, 3, 4, 5], 100) == 5

    def test_single_value(self):
        assert percentile([7], 99) == 7

    def test_empty_is_zero_not_error(self):
        assert percentile([], 50) == 0.0


class TestConcentration:
    def test_top_share(self):
        c = Counter({"a": 50, "b": 30, "c": 10, "d": 10})
        top, total, pct = concentration(c, 2)
        assert (top, total) == (80, 100) and pct == 80.0

    def test_top_n_larger_than_population(self):
        c = Counter({"a": 5})
        assert concentration(c, 10) == (5, 5, 100.0)

    def test_empty_does_not_divide_by_zero(self):
        assert concentration(Counter(), 5) == (0, 0, 0.0)


class TestHumanize:
    def test_units(self):
        assert humanize(45) == "45초"
        assert humanize(90) == "1.5분"
        assert humanize(7200) == "2.0시간"


class TestRecommendPause:
    """억제율은 유예에 단조 증가하므로 '최대'를 고르면 늘 후보 중 가장 긴 값이 나온다.
    유예 = 탐지 지연이므로 효과의 대부분을 확보하는 가장 짧은 값을 골라야 한다."""

    def test_picks_knee_not_maximum(self):
        # 1분 40% / 2분 55% / 5분 58% / 15분 60% → 최대 60%의 90%=54% 이상인 최소값 = 2분
        results = {1: (40, 100), 2: (55, 100), 5: (58, 100), 15: (60, 100)}
        assert recommend_pause(results) == 2

    def test_picks_shortest_when_all_equal(self):
        results = {1: (50, 100), 5: (50, 100), 15: (50, 100)}
        assert recommend_pause(results) == 1

    def test_picks_longest_when_gain_keeps_coming(self):
        # 계속 크게 오르면 긴 쪽이 필요하다
        results = {1: (10, 100), 5: (40, 100), 15: (100, 100)}
        assert recommend_pause(results) == 15

    def test_zero_suppression_falls_back_to_shortest(self):
        assert recommend_pause({1: (0, 100), 15: (0, 100)}) == 1

    def test_empty(self):
        assert recommend_pause({}) == 0

    def test_zero_total_does_not_divide_by_zero(self):
        assert recommend_pause({1: (0, 0), 5: (0, 0)}) == 1


class TestEndToEnd:
    """analyze() → render()가 실제 API 응답 형태로 동작하는지 (AWS 없이)."""

    def _item(self, name, minutes, state):
        return {
            "AlarmName": name,
            "Timestamp": at(minutes),
            "HistoryData": '{"newState":{"stateValue":"%s"}}' % state,
        }

    def _items(self):
        items = []
        # 짧게 자가 해소되는 알람 (auto-pause 대상) — 3회
        for i in range(3):
            items.append(self._item("[EC2] noisy CPU > 80 (TagName: i-1)", i * 100, "ALARM"))
            items.append(self._item("[EC2] noisy CPU > 80 (TagName: i-1)", i * 100 + 2, "OK"))
        # 오래 가는 진짜 장애 — 1회
        items.append(self._item("[RDS] real CPU > 80 (TagName: db-1)", 500, "ALARM"))
        items.append(self._item("[RDS] real CPU > 80 (TagName: db-1)", 560, "OK"))
        return items

    def _meta(self):
        return {
            "[EC2] noisy CPU > 80 (TagName: i-1)": {"metric": "CPUUtilization", "namespace": "AWS/EC2"},
            "[RDS] real CPU > 80 (TagName: db-1)": {"metric": "CPUUtilization", "namespace": "AWS/RDS"},
        }

    def test_analyze_counts_episodes_and_pause_effect(self):
        a = analyze(self._items(), self._meta(), T0, END)
        assert a["episodes"] == 4
        assert a["alarms_with_activity"] == 2
        assert a["unresolved"] == 0
        # 5분 유예면 2분짜리 3건은 억제, 60분짜리 1건은 통과
        assert a["pause"][5] == (3, 4)
        assert a["pause"][1] == (0, 4)      # 1분 유예로는 2분짜리를 못 잡는다
        assert a["by_namespace"]["AWS/EC2"] == 3

    def test_render_produces_report_without_error(self):
        a = analyze(self._items(), self._meta(), T0, END)
        out = render(a, "123456789012", "ap-northeast-2")
        assert "Auto-pause 효과" in out
        assert "Auto-pause 유예 후보: 2분" in out   # 2분이면 최대 효과의 90% 달성
        assert "noisy" in out and "AWS/EC2" in out

    def test_render_handles_empty_window(self):
        a = analyze([], {}, T0, END)
        out = render(a, "1", "r")
        assert "이 창에 발화가 없다" in out
