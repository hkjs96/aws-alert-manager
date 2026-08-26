"""
주간 메트릭 스냅샷 (daily_monitor/metric_snapshot.py) 테스트

- 알람 정의 → GetMetricData 쿼리 변환 (dynamic_dimensions 제외, 임계치 동봉)
- GetMetricData 배치/페이지네이션 결과 병합
- DDB 적재 (Decimal 변환, TTL, threshold_at_time)
- Orchestrator mode 전달 / Worker 라우팅
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from daily_monitor.metric_snapshot import (
    _build_queries_for_resource,
    _fetch_metric_data,
    _query_region,
    collect_weekly_snapshots,
)


def _ec2_resource(**over):
    base = {
        "resource_id": "i-001",
        "account_id": "123456789012",
        "type": "EC2",
        "region": "ap-northeast-2",
        "monitoring": True,
        "tags": {"Monitoring": "on", "Name": "srv", "Threshold_CPU": "90"},
    }
    base.update(over)
    return base


class TestBuildQueries:
    def test_ec2_excludes_dynamic_dimensions_and_carries_threshold(self):
        entries = _build_queries_for_resource(_ec2_resource())
        keys = {e["metric_key"] for e in entries}
        # disk_used_percent은 dynamic_dimensions → V1 제외
        assert keys == {"CPUUtilization", "mem_used_percent", "StatusCheckFailed"}

        cpu = next(e for e in entries if e["metric_key"] == "CPUUtilization")
        assert cpu["series_id"] == "123456789012#i-001#CPUUtilization"
        assert cpu["threshold"] == 90.0  # Threshold_CPU 태그 반영
        assert cpu["comparison"] == "GreaterThanThreshold"
        assert cpu["dimensions"] == [{"Name": "InstanceId", "Value": "i-001"}]

    def test_unknown_type_returns_empty(self):
        assert _build_queries_for_resource(_ec2_resource(type="Unknown")) == []


class TestQueryRegion:
    def test_regional_resource_uses_own_region(self):
        assert _query_region(_ec2_resource()) == "ap-northeast-2"

    def test_global_service_uses_us_east_1(self):
        r = _ec2_resource(type="CloudFront", region="ap-northeast-2")
        assert _query_region(r) == "us-east-1"


class TestFetchMetricData:
    def test_merges_stats_by_series_and_date(self):
        entries = [{
            "series_id": "acct#i-001#CPUUtilization",
            "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization",
            "dimensions": [{"Name": "InstanceId", "Value": "i-001"}],
        }]
        ts1 = datetime(2026, 8, 18, tzinfo=timezone.utc)
        ts2 = datetime(2026, 8, 19, tzinfo=timezone.utc)

        cw = MagicMock()
        cw.get_metric_data.return_value = {
            "MetricDataResults": [
                {"Id": "q0s0", "Timestamps": [ts1, ts2], "Values": [10.0, 20.0]},  # avg
                {"Id": "q0s6", "Timestamps": [ts1], "Values": [55.5]},             # p99
            ],
        }

        rows = _fetch_metric_data(cw, entries, ts1, ts2)
        assert rows["acct#i-001#CPUUtilization"]["2026-08-18"] == {"avg": 10.0, "p99": 55.5}
        assert rows["acct#i-001#CPUUtilization"]["2026-08-19"] == {"avg": 20.0}
        # 엔트리 1개 × 통계 7개 = 쿼리 7개 → 1콜
        assert cw.get_metric_data.call_count == 1
        sent = cw.get_metric_data.call_args.kwargs["MetricDataQueries"]
        assert len(sent) == 7
        assert {q["MetricStat"]["Stat"] for q in sent} == {
            "Average", "Maximum", "Minimum", "SampleCount", "p50", "p95", "p99",
        }

    def test_follows_next_token(self):
        entries = [{
            "series_id": "s", "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization", "dimensions": [],
        }]
        ts = datetime(2026, 8, 18, tzinfo=timezone.utc)
        cw = MagicMock()
        cw.get_metric_data.side_effect = [
            {"MetricDataResults": [{"Id": "q0s0", "Timestamps": [ts], "Values": [1.0]}],
             "NextToken": "t1"},
            {"MetricDataResults": [{"Id": "q0s1", "Timestamps": [ts], "Values": [9.0]}]},
        ]
        rows = _fetch_metric_data(cw, entries, ts, ts)
        assert rows["s"]["2026-08-18"] == {"avg": 1.0, "max": 9.0}
        assert cw.get_metric_data.call_count == 2


class TestCollectWeeklySnapshots:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("METRIC_HISTORY_TABLE", "metric-history-test")

    def _mock_cw_with(self, results):
        cw = MagicMock()
        cw.get_metric_data.return_value = {"MetricDataResults": results}
        session = MagicMock()
        session.client.return_value = cw
        return session, cw

    def test_skips_without_table_env(self, monkeypatch):
        monkeypatch.delenv("METRIC_HISTORY_TABLE")
        assert collect_weekly_snapshots([]) == {"skipped": "no_metric_history_table"}

    def test_writes_decimal_rows_with_ttl_and_threshold(self):
        ts = datetime(2026, 8, 18, tzinfo=timezone.utc)
        session, _cw = self._mock_cw_with([
            {"Id": "q0s0", "Timestamps": [ts], "Values": [42.5]},   # avg
            {"Id": "q0s6", "Timestamps": [ts], "Values": [88.8]},   # p99
        ])
        table = MagicMock()
        batch = table.batch_writer.return_value.__enter__.return_value
        ddb = MagicMock()
        ddb.Table.return_value = table
        accounts = [{"account_id": "123456789012", "role_arn": "", "regions": ["ap-northeast-2"]}]

        with patch("daily_monitor.metric_snapshot.discover_resources",
                   return_value=[_ec2_resource(), _ec2_resource(resource_id="i-off", monitoring=False)]), \
             patch("daily_monitor.metric_snapshot._get_session_for_account", return_value=session), \
             patch("daily_monitor.metric_snapshot.boto3.resource", return_value=ddb):
            stats = collect_weekly_snapshots(accounts)

        # monitoring=False 리소스는 제외
        assert stats["resources"] == 1
        assert stats["rows_written"] == 1

        item = batch.put_item.call_args.kwargs["Item"]
        assert item["series_id"] == "123456789012#i-001#CPUUtilization"
        assert item["period_start"] == "2026-08-18"
        # DDB는 float 불가 — Decimal로 적재돼야 한다
        assert item["avg"] == Decimal("42.5") and isinstance(item["avg"], Decimal)
        assert item["p99"] == Decimal("88.8")
        assert item["threshold_at_time"] == Decimal("90.0")
        assert item["comparison"] == "GreaterThanThreshold"
        assert isinstance(item["ttl"], int)
        # TTL ≈ 91일 후
        assert abs(item["ttl"] - (datetime.now(timezone.utc).timestamp() + 91 * 86400)) < 3600

    def test_discover_failure_returns_error(self):
        from botocore.exceptions import ClientError
        with patch(
            "daily_monitor.metric_snapshot.discover_resources",
            side_effect=ClientError({"Error": {"Code": "X", "Message": "y"}}, "Describe"),
        ):
            assert collect_weekly_snapshots([{"account_id": "1"}]) == {"error": "discover_failed"}


class TestOrchestratorModePassthrough:
    def test_mode_is_forwarded_to_worker_payload(self, monkeypatch):
        import json
        from daily_monitor import orchestrator as orch
        monkeypatch.setenv("WORKER_FUNCTION_NAME", "worker-fn")
        monkeypatch.setenv(
            "MONITORED_ACCOUNTS",
            '[{"account_id": "111", "role_arn": "arn:aws:iam::111:role/R"}]',
        )
        client = MagicMock()
        with patch.object(orch, "_get_lambda_client", return_value=client):
            orch.lambda_handler({"mode": "metric_snapshot"}, None)
        payload = json.loads(client.invoke.call_args.kwargs["Payload"].decode())
        assert payload["mode"] == "metric_snapshot"
        assert payload["account_id"] == "111"

    def test_no_mode_keeps_plain_account_payload(self, monkeypatch):
        import json
        from daily_monitor import orchestrator as orch
        monkeypatch.setenv("WORKER_FUNCTION_NAME", "worker-fn")
        monkeypatch.setenv("MONITORED_ACCOUNTS", '[{"account_id": "111", "role_arn": ""}]')
        client = MagicMock()
        with patch.object(orch, "_get_lambda_client", return_value=client):
            orch.lambda_handler({}, None)
        payload = json.loads(client.invoke.call_args.kwargs["Payload"].decode())
        assert "mode" not in payload


class TestWorkerRouting:
    def test_metric_snapshot_mode_routes_to_handler(self, monkeypatch):
        from daily_monitor import lambda_handler as lh
        monkeypatch.setenv("METRIC_HISTORY_TABLE", "t")
        with patch.object(lh, "_resolve_accounts_for_inventory",
                          return_value=[{"account_id": "111", "role_arn": "", "regions": ["us-east-1"]}]), \
             patch("daily_monitor.metric_snapshot.collect_weekly_snapshots",
                   return_value={"rows_written": 3}) as mock_collect:
            result = lh.lambda_handler({"mode": "metric_snapshot", "account_id": "111"}, None)
        assert result["status"] == "ok"
        assert result["rows_written"] == 3
        mock_collect.assert_called_once()
