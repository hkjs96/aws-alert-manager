"""
MetricBatch (record → execute → serve) 테스트

query_metric 관문 배치가 라이브 경로와 동일한 값 의미론을 유지하는지,
미등록/실패 쿼리가 라이브 폴백으로 이어지는지 검증한다.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from common.collectors.base import (
    MetricBatch,
    query_metric,
    set_active_metric_batch,
)

_DIMS = [{"Name": "InstanceId", "Value": "i-001"}]
_START = datetime(2026, 8, 25, tzinfo=timezone.utc)
_END = datetime(2026, 8, 25, 0, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_batch():
    set_active_metric_batch(None)
    yield
    set_active_metric_batch(None)


class TestKey:
    def test_dimension_order_insensitive(self):
        d1 = [{"Name": "A", "Value": "1"}, {"Name": "B", "Value": "2"}]
        d2 = [{"Name": "B", "Value": "2"}, {"Name": "A", "Value": "1"}]
        assert MetricBatch.key_for("NS", "M", d1, "Average") == \
            MetricBatch.key_for("NS", "M", d2, "Average")

    def test_stat_differentiates(self):
        assert MetricBatch.key_for("NS", "M", _DIMS, "Average") != \
            MetricBatch.key_for("NS", "M", _DIMS, "Sum")


class TestRecord:
    def test_recording_registers_and_returns_none_without_api(self):
        batch = MetricBatch()
        batch.record()
        set_active_metric_batch(batch)

        mock_cw = MagicMock()
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            value = query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END)

        assert value is None
        mock_cw.get_metric_statistics.assert_not_called()
        assert len(batch._pending) == 1


class TestExecute:
    def _batch_with_query(self):
        batch = MetricBatch()
        batch.record()
        batch.register("AWS/EC2", "CPUUtilization", _DIMS, "Average")
        return batch

    def test_latest_datapoint_semantics(self):
        """ScanBy 내림차순 → Values[0]이 최신값 (라이브 경로의 max-timestamp와 동일)."""
        batch = self._batch_with_query()
        cw = MagicMock()
        cw.get_metric_data.return_value = {
            "MetricDataResults": [{"Id": "q0", "Values": [77.7, 55.5, 11.1]}],
        }
        calls = batch.execute(cw=cw)

        assert calls == 1
        kwargs = cw.get_metric_data.call_args.kwargs
        assert kwargs["ScanBy"] == "TimestampDescending"
        assert kwargs["MetricDataQueries"][0]["MetricStat"]["Period"] == 300

        batch.serve()
        set_active_metric_batch(batch)
        assert query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END) == 77.7

    def test_empty_values_cached_as_none(self):
        batch = self._batch_with_query()
        cw = MagicMock()
        cw.get_metric_data.return_value = {
            "MetricDataResults": [{"Id": "q0", "Values": []}],
        }
        batch.execute(cw=cw)
        batch.serve()
        set_active_metric_batch(batch)

        live = MagicMock()
        with patch("common.collectors.base._get_cw_client", return_value=live):
            value = query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END)

        # "데이터 없음"이 캐시된 것 — 라이브 재조회 없이 None
        assert value is None
        live.get_metric_statistics.assert_not_called()

    def test_next_token_upgrades_none_to_value(self):
        batch = self._batch_with_query()
        cw = MagicMock()
        cw.get_metric_data.side_effect = [
            {"MetricDataResults": [{"Id": "q0", "Values": []}], "NextToken": "t"},
            {"MetricDataResults": [{"Id": "q0", "Values": [42.0]}]},
        ]
        batch.execute(cw=cw)
        assert batch.lookup(MetricBatch.key_for("AWS/EC2", "CPUUtilization", _DIMS, "Average")) \
            == (True, 42.0)

    def test_chunks_by_500(self):
        batch = MetricBatch()
        batch.record()
        for i in range(501):
            batch.register("AWS/EC2", f"M{i}", _DIMS, "Average")
        cw = MagicMock()
        cw.get_metric_data.return_value = {"MetricDataResults": []}
        calls = batch.execute(cw=cw)
        assert calls == 2
        first = cw.get_metric_data.call_args_list[0].kwargs["MetricDataQueries"]
        second = cw.get_metric_data.call_args_list[1].kwargs["MetricDataQueries"]
        assert len(first) == 500 and len(second) == 1


class TestServeFallback:
    def test_unregistered_query_falls_back_to_live(self):
        """record에 없던 쿼리(조건 분기 차이)는 serve에서 라이브 경로로 간다."""
        batch = MetricBatch()
        batch.record()
        batch.serve()
        set_active_metric_batch(batch)

        live = MagicMock()
        live.get_metric_statistics.return_value = {
            "Datapoints": [
                {"Timestamp": _START, "Average": 33.3},
                {"Timestamp": _END, "Average": 66.6},
            ],
        }
        with patch("common.collectors.base._get_cw_client", return_value=live):
            value = query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END)

        assert value == 66.6  # 최신 타임스탬프 값
        live.get_metric_statistics.assert_called_once()

    def test_failed_chunk_keys_fall_back_to_live(self):
        from botocore.exceptions import ClientError as CE
        batch = MetricBatch()
        batch.record()
        batch.register("AWS/EC2", "CPUUtilization", _DIMS, "Average")
        cw = MagicMock()
        cw.get_metric_data.side_effect = CE(
            {"Error": {"Code": "Throttling", "Message": "x"}}, "GetMetricData",
        )
        batch.execute(cw=cw)  # 실패 → 캐시 미설정
        batch.serve()
        set_active_metric_batch(batch)

        live = MagicMock()
        live.get_metric_statistics.return_value = {
            "Datapoints": [{"Timestamp": _END, "Average": 12.5}],
        }
        with patch("common.collectors.base._get_cw_client", return_value=live):
            value = query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END)

        assert value == 12.5
        live.get_metric_statistics.assert_called_once()

    def test_no_batch_is_pure_live_path(self):
        live = MagicMock()
        live.get_metric_statistics.return_value = {"Datapoints": []}
        with patch("common.collectors.base._get_cw_client", return_value=live):
            assert query_metric("AWS/EC2", "CPUUtilization", _DIMS, _START, _END) is None
        live.get_metric_statistics.assert_called_once()
