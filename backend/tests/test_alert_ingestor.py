"""
Alert Ingestor (alert_ingestor/lambda_handler.py) 테스트

이 핸들러가 이벤트를 버리면 되돌릴 수 없다(R2-1). 그래서:
- 어떤 형태의 이벤트든 적재된다 (관리 대상 아님·파싱 실패 포함)
- 적재 실패는 **예외를 올린다** — EventBridge 재시도/DLQ가 안전망이므로 삼키면 안 된다
- 고객사 매핑이 없어도 이벤트는 남는다
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from tests.test_alert_event import state_change_event


@pytest.fixture(autouse=True)
def _reset_caches():
    from alert_ingestor import lambda_handler as lh
    lh._get_ddb.cache_clear()
    lh._account_to_customer.cache_clear()
    yield
    lh._get_ddb.cache_clear()
    lh._account_to_customer.cache_clear()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "event-history-test")
    monkeypatch.setenv("ACCOUNTS_TABLE", "accounts-test")


def _ddb_with(accounts_items=None, history=None):
    """{테이블명: mock} 매핑을 가진 DynamoDB 리소스 mock."""
    accounts = MagicMock()
    accounts.scan.return_value = {"Items": accounts_items or []}
    hist = history or MagicMock()
    ddb = MagicMock()
    ddb.Table.side_effect = lambda name: {
        "accounts-test": accounts, "event-history-test": hist,
    }[name]
    return ddb, hist


class TestIngest:
    def test_writes_normalized_item(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(
            accounts_items=[{"account_id": "111122223333", "customer_id": "cust-1"}])
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["status"] == "ok"
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["series_id"] == "111122223333#i-0abc#CPUUtilization"
        assert item["state"] == "ALARM"
        assert item["customer_id"] == "cust-1"
        assert item["customer_day"] == "cust-1#2026-09-02"
        assert item["suppressed"] is False        # 정제 이전 기록 (R2-1)
        assert "raw" in item                      # 원본 보존 (R2-5)

    def test_unknown_account_still_ingests(self, env):
        """고객사 매핑이 없다고 이벤트를 버리면 안 된다."""
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(accounts_items=[])
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["status"] == "ok"
        item = hist.put_item.call_args.kwargs["Item"]
        assert "customer_id" not in item          # 빈 값은 넣지 않는다
        assert item["customer_day"].startswith("#")
        assert item["state"] == "ALARM"

    def test_unmanaged_alarm_is_ingested(self, env):
        """고객사 자체 알람도 이력에는 남는다."""
        from alert_ingestor import lambda_handler as lh

        e = state_change_event()
        e["detail"]["alarmName"] = "customer-own-alarm"
        e["detail"]["configuration"].pop("description")
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(e, None)

        assert result["status"] == "ok"
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["alarm_name"] == "customer-own-alarm"
        assert item["parse_error"] == "unmanaged alarm format"

    def test_malformed_event_is_ingested(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler({"id": "x", "detail": "not a dict"}, None)

        assert result["status"] == "ok"
        assert hist.put_item.called
        assert hist.put_item.call_args.kwargs["Item"]["parse_error"]

    def test_config_change_is_ingested(self, env):
        from alert_ingestor import lambda_handler as lh

        e = state_change_event()
        e["detail-type"] = "CloudWatch Alarm Configuration Change"
        e["detail"]["operation"] = "delete"
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(e, None)

        item = hist.put_item.call_args.kwargs["Item"]
        assert item["event_type"] == "config_change" and item["operation"] == "delete"


class TestFailureModes:
    def test_put_failure_raises_so_eventbridge_retries(self, env):
        """적재 실패를 삼키면 EventBridge 재시도·DLQ 안전망이 무력해진다."""
        from alert_ingestor import lambda_handler as lh

        hist = MagicMock()
        hist.put_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
            "PutItem")
        ddb, _ = _ddb_with(history=hist)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            with pytest.raises(ClientError):
                lh.lambda_handler(state_change_event(), None)

    def test_missing_table_env_does_not_crash(self, monkeypatch):
        from alert_ingestor import lambda_handler as lh

        monkeypatch.delenv("EVENT_HISTORY_TABLE", raising=False)
        result = lh.lambda_handler(state_change_event(), None)
        assert result == {"status": "skipped", "reason": "no_table"}

    def test_accounts_scan_failure_does_not_block_ingest(self, env):
        """매핑 조회가 실패해도 이벤트는 적재되어야 한다."""
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "Scan")
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist}[name]

        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["status"] == "ok" and hist.put_item.called


class TestAccountMappingCache:
    def test_mapping_is_scanned_once_per_container(self, env):
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.return_value = {"Items": [
            {"account_id": "111122223333", "customer_id": "cust-1"}]}
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist}[name]

        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)
            lh.lambda_handler(state_change_event(), None)

        assert accounts.scan.call_count == 1      # 이벤트마다 스캔하지 않는다
        assert hist.put_item.call_count == 2

    def test_mapping_paginates(self, env):
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.side_effect = [
            {"Items": [{"account_id": "a1", "customer_id": "c1"}], "LastEvaluatedKey": {"k": 1}},
            {"Items": [{"account_id": "111122223333", "customer_id": "c2"}]},
        ]
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist}[name]

        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)

        assert accounts.scan.call_count == 2
        assert hist.put_item.call_args.kwargs["Item"]["customer_id"] == "c2"
