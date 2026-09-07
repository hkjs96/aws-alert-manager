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
    lh._reset_account_cache()
    lh._policy.cache_clear()
    yield
    lh._get_ddb.cache_clear()
    lh._reset_account_cache()
    lh._policy.cache_clear()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "event-history-test")
    monkeypatch.setenv("ACCOUNTS_TABLE", "accounts-test")


def _ddb_with(accounts_items=None, history=None, prior_events=None):
    """{테이블명: mock} 매핑을 가진 DynamoDB 리소스 mock.

    prior_events: 중복 판정에 쓰이는 `_last_notified_at` 조회가 돌려줄 과거 항목들
    (최신순). 지정하지 않으면 과거 기록 없음.
    """
    accounts = MagicMock()
    accounts.scan.return_value = {"Items": accounts_items or []}
    hist = history or MagicMock()
    hist.query.return_value = {"Items": prior_events or []}
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

    def test_mapping_refreshes_after_ttl(self, env):
        """새 고객사 등록이 컨테이너 수명 동안 묻히면 안 된다 (review-2026-09-07 Q2)."""
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.side_effect = [
            {"Items": []},                                                       # 처음엔 미등록
            {"Items": [{"account_id": "111122223333", "customer_id": "new-cust"}]},
        ]
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist}[name]
        clock = [1000.0]

        with patch.object(lh, "_get_ddb", return_value=ddb), \
                patch.object(lh, "_monotonic", side_effect=lambda: clock[0]):
            lh.lambda_handler(state_change_event(), None)
            assert hist.put_item.call_args.kwargs["Item"].get("customer_id") is None

            clock[0] += lh.ACCOUNT_CACHE_TTL_SEC - 1
            lh.lambda_handler(state_change_event(), None)          # TTL 안 — 재스캔 없음
            assert accounts.scan.call_count == 1

            clock[0] += 2
            lh.lambda_handler(state_change_event(), None)          # TTL 경과 — 재스캔
        assert accounts.scan.call_count == 2
        assert hist.put_item.call_args.kwargs["Item"]["customer_id"] == "new-cust"

    def test_scan_failure_keeps_previous_mapping(self, env):
        """일시 장애에 빈 매핑으로 덮으면 그동안 모든 이벤트가 고객사를 잃는다."""
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.side_effect = [
            {"Items": [{"account_id": "111122223333", "customer_id": "cust-1"}]},
            ClientError({"Error": {"Code": "ProvisionedThroughputExceededException",
                                   "Message": "slow down"}}, "Scan"),
            {"Items": [{"account_id": "111122223333", "customer_id": "cust-1"}]},
        ]
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist}[name]
        clock = [1000.0]

        with patch.object(lh, "_get_ddb", return_value=ddb), \
                patch.object(lh, "_monotonic", side_effect=lambda: clock[0]):
            lh.lambda_handler(state_change_event(), None)
            clock[0] += lh.ACCOUNT_CACHE_TTL_SEC + 1
            lh.lambda_handler(state_change_event(), None)          # 스캔 실패 → 이전 매핑 유지
            assert hist.put_item.call_args.kwargs["Item"]["customer_id"] == "cust-1"
            lh.lambda_handler(state_change_event(), None)          # 실패 직후엔 재시도하지 않는다
            assert accounts.scan.call_count == 2
            clock[0] += lh.ACCOUNT_CACHE_TTL_SEC + 1
            lh.lambda_handler(state_change_event(), None)          # TTL 뒤 재시도
        assert accounts.scan.call_count == 3


class TestShadowVerdict:
    """정제 판정을 기록만 하고 실행하지 않는다 (Shadow). 발송자가 붙기 전에
    실제 트래픽으로 억제율을 측정하기 위함이다."""

    def test_firing_state_change_is_notify(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify"
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["suppressed"] is False
        assert "suppression_reason" not in item      # 빈 값은 넣지 않는다

    def test_config_change_is_recorded_but_not_actionable(self, env):
        """알람 생성/수정/삭제는 감사용으로 남기되 사람을 깨우지 않는다."""
        from alert_ingestor import lambda_handler as lh

        e = state_change_event()
        e["detail-type"] = "CloudWatch Alarm Configuration Change"
        e["detail"]["operation"] = "update"
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(e, None)

        assert result["action"] == "suppress" and result["reason"] == "not_actionable"
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["suppressed"] is True
        assert item["suppression_reason"] == "not_actionable"

    def test_severity_is_derived_from_metric(self, env):
        """알람 이벤트에는 태그가 없다 — 메트릭 키의 기본 등급을 쓴다."""
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)

        # CPUUtilization은 레지스트리 기본 등급이 있다
        assert hist.put_item.call_args.kwargs["Item"]["severity"].startswith("SEV-")

    def test_dedup_uses_prior_notified_event(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(prior_events=[
            {"suppressed": False, "occurred_at": "2026-09-02T10:00:00Z"},
        ])
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)   # 10:15 발생

        assert result["action"] == "suppress" and result["reason"] == "dedup"
        # 조회는 최신순으로 제한된 건수만 (전체 스캔 금지)
        kwargs = hist.query.call_args.kwargs
        assert kwargs["ScanIndexForward"] is False and kwargs["Limit"] == 20

    def test_prior_suppressed_events_do_not_count_as_notified(self, env):
        """억제된 과거 기록은 '보낸 적 있음'이 아니다 — 세면 영구히 막힌다."""
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(prior_events=[
            {"suppressed": True, "occurred_at": "2026-09-02T10:00:00Z"},
        ])
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify"

    def test_last_notified_lookup_failure_does_not_suppress(self, env):
        """조회가 실패하면 중복 위험을 감수하고 보낸다 — 알림을 잃는 것보다 낫다."""
        from alert_ingestor import lambda_handler as lh

        hist = MagicMock()
        hist.query.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "Query")
        ddb, _ = _ddb_with(history=hist)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and hist.put_item.called

    def test_deferred_is_not_counted_as_suppressed(self, env, monkeypatch):
        """DEFER는 타이머가 붙기 전까지 실행 불가 — 억제로 세면 억제율이 과대 집계된다."""
        from alert_ingestor import lambda_handler as lh

        monkeypatch.setenv("ALERT_AUTO_PAUSE_SEC", '{"SEV-3": 300, "SEV-5": 300}')
        lh._policy.cache_clear()
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "defer"
        assert hist.put_item.call_args.kwargs["Item"]["suppressed"] is False

    def test_malformed_pause_config_is_ignored(self, env, monkeypatch):
        """설정 오타가 수집을 멈추면 안 된다."""
        from alert_ingestor import lambda_handler as lh

        monkeypatch.setenv("ALERT_AUTO_PAUSE_SEC", "{not json")
        lh._policy.cache_clear()
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and hist.put_item.called
