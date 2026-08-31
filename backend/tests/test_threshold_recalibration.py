"""
임계치 재보정 Shadow 모드 (common/threshold_recalibration.py) 테스트

- 산식: 28일 일 p99 최댓값 × 1.2 → 클램프 → 변화율 ±25% → 5% 히스테리시스
- 대상 필터: GreaterThanThreshold + 정책 표 메트릭 + SEV-1/2 제외
- 효과 추정: 일 max 기준 현재/제안 임계치 초과 일수
- 잡: 대상 아닌 시리즈는 DDB 조회 없음, insufficient_data는 행 미기록, shadow 행에 threshold_value 없음
- Worker 라우팅 (mode=threshold_recalibration)
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from common.threshold_recalibration import (
    HEADROOM,
    MIN_DAYS,
    is_recalibration_candidate,
    propose_threshold,
    run_shadow_recalibration,
)


def _rows(p99s, maxes=None):
    maxes = maxes or [v * 1.5 for v in p99s]
    return [
        {"period_start": f"2026-08-{i + 1:02d}", "p99": Decimal(str(p)), "max": Decimal(str(m))}
        for i, (p, m) in enumerate(zip(p99s, maxes))
    ]


class TestCandidate:
    def test_filters(self):
        assert is_recalibration_candidate("RequestCount", "GreaterThanThreshold", "SEV-4") == (True, "")
        assert is_recalibration_candidate("RequestCount", "LessThanThreshold", "SEV-4")[1] == "excluded_comparison"
        assert is_recalibration_candidate("RequestCount", "GreaterThanThreshold", "SEV-2")[1] == "excluded_severity"
        assert is_recalibration_candidate("HTTPCode_ELB_5XX_Count", "GreaterThanThreshold", "SEV-4")[1] == "excluded_metric"
        assert is_recalibration_candidate("StatusCheckFailed", "GreaterThanThreshold", "SEV-1")[1] == "excluded_severity"


class TestPropose:
    def test_traffic_proposal_from_max_daily_p99(self):
        # 현재 10,000 고정 — 실제 p99 최고 3,000 → 3,600 제안이지만 변화율 상한(-25%)에 걸려 7,500
        rows = _rows([2000.0] * 27 + [3000.0], maxes=[2500.0] * 27 + [9000.0])
        p = propose_threshold(metric_key="RequestCount", comparison="GreaterThanThreshold",
                              current=10000.0, severity="SEV-4", rows=rows)
        assert p.status == "proposed"
        assert p.base_p99 == 3000.0
        assert p.proposed == 7500.0
        assert p.reasons == ["p99x1.2", "rate_capped"]
        assert p.days_available == 28
        assert p.breach_days_current == 0          # 일 max가 10,000을 넘은 날 없음
        assert p.breach_days_proposed == 1         # 9,000 > 7,500 하루

    def test_uncapped_when_within_rate_band(self):
        rows = _rows([100.0] * 25)
        p = propose_threshold(metric_key="TargetResponseTime", comparison="GreaterThanThreshold",
                              current=110.0, severity="SEV-4", rows=rows)
        assert p.status == "proposed" and p.proposed == 120.0     # 100 × 1.2, 110 대비 +9%
        assert p.reasons == ["p99x1.2"]

    def test_cpu_is_clamped_to_absolute_floor(self):
        # p99 30% → 36%이지만 CPU는 70% 아래로 내려가지 않는다; 현재 80 → -25% 상한은 60이라 70이 유효
        rows = _rows([30.0] * 28)
        p = propose_threshold(metric_key="CPUUtilization", comparison="GreaterThanThreshold",
                              current=80.0, severity="SEV-3", rows=rows)
        assert p.status == "proposed" and p.proposed == 70.0
        assert p.reasons == ["p99x1.2", "clamped_lo"]

    def test_cpu_ceiling(self):
        # 90 × 1.2 = 108 → 상한 95; 현재 85 대비 +11.8%라 히스테리시스 밖 → 95 제안
        rows = _rows([90.0] * 28)
        p = propose_threshold(metric_key="CPUUtilization", comparison="GreaterThanThreshold",
                              current=85.0, severity="SEV-3", rows=rows)
        assert p.status == "proposed" and p.proposed == 95.0
        assert p.reasons == ["p99x1.2", "clamped_hi"]

    def test_cpu_ceiling_within_hysteresis_holds(self):
        # 같은 데이터, 현재 92 → 95는 +3.3%라 유지
        rows = _rows([90.0] * 28)
        p = propose_threshold(metric_key="CPUUtilization", comparison="GreaterThanThreshold",
                              current=92.0, severity="SEV-3", rows=rows)
        assert p.status == "hold" and p.reason == "hysteresis" and p.proposed == 92.0

    def test_hysteresis_holds_small_change(self):
        rows = _rows([84.0] * 28)   # 84 × 1.2 = 100.8 → 현재 100 대비 +0.8%
        p = propose_threshold(metric_key="RequestCount", comparison="GreaterThanThreshold",
                              current=100.0, severity="SEV-4", rows=rows)
        assert p.status == "hold" and p.reason == "hysteresis"
        assert p.proposed == 100.0 and "hysteresis" in p.reasons

    def test_insufficient_data(self):
        rows = _rows([100.0] * (MIN_DAYS - 1))
        p = propose_threshold(metric_key="RequestCount", comparison="GreaterThanThreshold",
                              current=100.0, severity="SEV-4", rows=rows)
        assert p.status == "hold" and p.reason == "insufficient_data"
        assert p.days_available == MIN_DAYS - 1 and p.proposed is None

    def test_excluded_reports_reason(self):
        p = propose_threshold(metric_key="RequestCount", comparison="GreaterThanThreshold",
                              current=1.0, severity="SEV-1", rows=_rows([1.0] * 28))
        assert p.status == "excluded" and p.reason == "excluded_severity"

    def test_rounding(self):
        rows = _rows([0.0421] * 28)
        p = propose_threshold(metric_key="TargetResponseTime", comparison="GreaterThanThreshold",
                              current=0.045, severity="SEV-4", rows=rows)
        assert p.proposed == pytest.approx(0.0505, abs=1e-4)   # 0.0421×1.2=0.05052 → 유효숫자 3
        assert HEADROOM == 1.2


class TestJob:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("METRIC_HISTORY_TABLE", "hist")
        monkeypatch.setenv("THRESHOLD_OVERRIDES_TABLE", "ovr")

    def _alb(self, rid="arn:aws:elasticloadbalancing:ap-northeast-2:1:loadbalancer/app/web/abc"):
        return {"resource_id": rid, "account_id": "1", "type": "ALB", "region": "ap-northeast-2",
                "monitoring": True, "tags": {"Monitoring": "on"}}

    def test_skips_without_env(self, monkeypatch):
        monkeypatch.delenv("THRESHOLD_OVERRIDES_TABLE")
        assert run_shadow_recalibration([]) == {"skipped": "missing_table_env"}

    def test_writes_shadow_rows_only_for_candidates_with_data(self):
        hist = MagicMock()
        rows_by_series = {
            "1#arn:aws:elasticloadbalancing:ap-northeast-2:1:loadbalancer/app/web/abc#RequestCount":
                _rows([2000.0] * 28),
            "1#arn:aws:elasticloadbalancing:ap-northeast-2:1:loadbalancer/app/web/abc#TargetResponseTime":
                _rows([0.5] * 5),   # 부족
        }
        hist.query.side_effect = lambda **kw: {
            "Items": rows_by_series.get(kw["KeyConditionExpression"]._values[0]._values[1], [])
        }
        ovr = MagicMock()
        batch = ovr.batch_writer.return_value.__enter__.return_value
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {"hist": hist, "ovr": ovr}[name]

        entries = [
            {"series_id": k, "metric_key": k.rsplit("#", 1)[1], "resource_id": self._alb()["resource_id"],
             "resource_type": "ALB", "account_id": "1", "comparison": "GreaterThanThreshold",
             "threshold": 10000.0 if k.endswith("RequestCount") else 1.0}
            for k in rows_by_series
        ] + [
            {"series_id": "1#x#HTTPCode_ELB_5XX_Count", "metric_key": "HTTPCode_ELB_5XX_Count",
             "resource_id": "x", "resource_type": "ALB", "account_id": "1",
             "comparison": "GreaterThanThreshold", "threshold": 10.0},
        ]
        with patch("common.threshold_recalibration.discover_resources", return_value=[self._alb()]), \
             patch("common.threshold_recalibration._build_queries_for_resource", return_value=entries), \
             patch("common.threshold_recalibration.boto3.resource", return_value=ddb):
            stats = run_shadow_recalibration(
                [{"account_id": "1"}], now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )

        assert stats["series"] == 3
        assert stats["excluded"] == 1            # 5XX 카운트 — DDB 조회 없음
        assert stats["queries"] == 2
        assert stats["proposed"] == 1
        assert stats["insufficient_data"] == 1
        assert stats["rows_written"] == 1

        item = batch.put_item.call_args.kwargs["Item"]
        assert item["scope_id"].startswith("resource_id:arn:aws:elasticloadbalancing")
        assert item["metric_key"] == "RequestCount"
        assert item["status"] == "shadow" and item["proposal_status"] == "proposed"
        assert item["current_threshold"] == Decimal("10000.0")
        assert item["proposed_threshold"] == Decimal("7500.0")   # 2,400 제안 → -25% 상한
        assert item["proposal_reasons"] == ["p99x1.2", "rate_capped"]
        assert "threshold_value" not in item                    # 고객사 오버라이드로 오인 금지
        assert isinstance(item["ttl"], int)
        # 조회 창: now - 28일
        since = hist.query.call_args.kwargs["KeyConditionExpression"]._values[1]._values[1]
        assert since == "2026-08-04"


class TestWorkerRouting:
    def test_mode_routes_to_recalibration(self, monkeypatch):
        from daily_monitor import lambda_handler as lh

        with patch.object(lh, "_resolve_accounts_for_inventory",
                          return_value=[{"account_id": "111", "role_arn": "", "regions": ["us-east-1"]}]), \
             patch("common.threshold_recalibration.run_shadow_recalibration",
                   return_value={"proposed": 2}) as mock_run:
            result = lh.lambda_handler({"mode": "threshold_recalibration", "account_id": "111"}, None)
        assert result["status"] == "ok" and result["proposed"] == 2
        mock_run.assert_called_once()
