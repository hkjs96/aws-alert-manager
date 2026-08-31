"""
타임아웃으로 finish 기록 없이 running으로 남은 run history 정정 테스트

- 워커: _mark_stale_runs — 시작 시 20분 이상 running인 과거 run을 timeout으로 영속 정정
- API: _with_derived_status — 조회 시점 파생 상태 (워커 정정 전에도 유령 running 방지)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from botocore.exceptions import ClientError


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class TestMarkStaleRuns:
    def test_old_running_run_is_marked_timeout(self):
        from daily_monitor import lambda_handler as lh
        now = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
        table = MagicMock()
        table.query.return_value = {"Items": [
            {"scope": "daily_monitor", "started_at": _iso(now - timedelta(hours=1)),
             "run_id": "daily-monitor#self#stale", "status": "running"},
        ]}

        fixed = lh._mark_stale_runs(table, now_ts=now.timestamp())

        assert fixed == 1
        kw = table.update_item.call_args.kwargs
        assert kw["Key"] == {"scope": "daily_monitor", "started_at": _iso(now - timedelta(hours=1))}
        assert kw["ExpressionAttributeValues"][":status"] == "timeout"
        # 그 사이 finish가 기록된 run은 덮어쓰지 않도록 조건부 갱신
        assert kw["ConditionExpression"] == "#s = :running"

    def test_query_window_excludes_current_run(self):
        """조회 범위가 [now-7일, now-20분]이어야 방금 시작한 run이 대상이 되지 않는다."""
        from boto3.dynamodb.conditions import ConditionExpressionBuilder
        from daily_monitor import lambda_handler as lh
        now = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
        table = MagicMock()
        table.query.return_value = {"Items": []}
        lh._mark_stale_runs(table, now_ts=now.timestamp())

        cond = table.query.call_args.kwargs["KeyConditionExpression"]
        built = ConditionExpressionBuilder().build_expression(cond, is_key_condition=True)
        bounds = set(built.attribute_value_placeholders.values())
        assert "2026-08-24T06:00:00Z" in bounds   # lookback: now - 7일
        assert "2026-08-31T05:40:00Z" in bounds   # cutoff: now - 20분

    def test_conditional_check_failure_is_skipped_quietly(self):
        from daily_monitor import lambda_handler as lh
        table = MagicMock()
        table.query.return_value = {"Items": [
            {"scope": "daily_monitor", "started_at": "2026-08-31T04:38:08Z", "status": "running"},
        ]}
        table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "UpdateItem",
        )
        assert lh._mark_stale_runs(table, now_ts=datetime(2026, 8, 31, 6, tzinfo=timezone.utc).timestamp()) == 0

    def test_query_error_returns_zero(self):
        from daily_monitor import lambda_handler as lh
        table = MagicMock()
        table.query.side_effect = ClientError({"Error": {"Code": "X", "Message": "y"}}, "Query")
        assert lh._mark_stale_runs(table) == 0
        table.update_item.assert_not_called()

    def test_no_table_is_noop(self):
        from daily_monitor import lambda_handler as lh
        assert lh._mark_stale_runs(None) == 0

    def test_follows_pagination(self):
        from daily_monitor import lambda_handler as lh
        table = MagicMock()
        table.query.side_effect = [
            {"Items": [{"started_at": "2026-08-30T01:00:00Z", "status": "running"}],
             "LastEvaluatedKey": {"k": 1}},
            {"Items": [{"started_at": "2026-08-30T02:00:00Z", "status": "running"}]},
        ]
        assert lh._mark_stale_runs(table, now_ts=datetime(2026, 8, 31, 6, tzinfo=timezone.utc).timestamp()) == 2
        assert table.update_item.call_count == 2


class TestDerivedStatus:
    def _items(self, now):
        return [
            {"status": "running", "started_at": _iso(now - timedelta(minutes=30))},   # stale
            {"status": "running", "started_at": _iso(now - timedelta(minutes=5))},    # 진행 중
            {"status": "success", "started_at": _iso(now - timedelta(hours=2))},
            {"status": "running", "started_at": "not-a-date"},
        ]

    def test_only_old_running_becomes_timeout(self):
        from api_handler.routes.monitor_runs import _with_derived_status
        now = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
        out = _with_derived_status(self._items(now), now=now)
        assert out[0]["status"] == "timeout" and out[0]["stale"] is True
        assert out[1]["status"] == "running" and "stale" not in out[1]
        assert out[2]["status"] == "success"
        assert out[3]["status"] == "running"  # 파싱 불가 → 건드리지 않음

    def test_naive_timestamp_treated_as_utc(self):
        from api_handler.routes.monitor_runs import _parse_iso
        parsed = _parse_iso("2026-08-31T04:38:08")
        assert parsed is not None and parsed.tzinfo is not None
