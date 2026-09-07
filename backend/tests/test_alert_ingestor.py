"""
Alert Ingestor (alert_ingestor/lambda_handler.py) 테스트

이 핸들러가 이벤트를 버리면 되돌릴 수 없다(R2-1). 그래서:
- 어떤 형태의 이벤트든 적재된다 (관리 대상 아님·파싱 실패 포함)
- 적재 실패는 **예외를 올린다** — EventBridge 재시도/DLQ가 안전망이므로 삼키면 안 된다
- 고객사 매핑이 없어도 이벤트는 남는다

판정 재료는 상태 테이블(D9)에서 온다:
- 상태 먼저, 이력 나중 — 재시도에 안전한 순서
- 조건부 갱신 충돌 → 재판정 → dedup / 소진 → fail-open NOTIFY
- 상태 조회·갱신 실패는 fail-open이되 `state_ok=False`로 드러난다
- 가짜 DynamoDB(조건식 해석)로 25번 토글 시나리오를 핸들러 수준에서 재현
"""

from datetime import datetime, timedelta, timezone
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
    monkeypatch.setenv("ALERT_STATE_TABLE", "alert-state-test")


def _conditional_failure():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
                       "PutItem")


class FakeStateTable:
    """조건식을 해석하는 인메모리 상태 테이블 — 낙관적 잠금 동작을 실제처럼 검증하기 위해."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.puts = 0

    def get_item(self, Key, **_):
        it = self.items.get(Key["state_key"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        cur = self.items.get(Item["state_key"])
        if ConditionExpression is not None:
            expr = ConditionExpression.get_expression()
            op, values = expr["operator"], expr["values"]
            if op == "attribute_not_exists":
                ok = cur is None
            elif op == "=":
                ok = cur is not None and cur.get(values[0].name) == values[1]
            else:
                raise AssertionError(f"unsupported condition {op}")
            if not ok:
                raise _conditional_failure()
        self.items[Item["state_key"]] = dict(Item)
        self.puts += 1


def _ddb_with(accounts_items=None, history=None, state_item=None, state=None):
    """{테이블명: mock} 매핑을 가진 DynamoDB 리소스 mock. 상태 테이블은 `state`로 주입하거나
    `state_item`으로 GetItem 응답만 고정한다."""
    accounts = MagicMock()
    accounts.scan.return_value = {"Items": accounts_items or []}
    hist = history or MagicMock()
    st = state if state is not None else MagicMock()
    if state is None:
        st.get_item.return_value = {"Item": state_item} if state_item else {}
    tables = {"accounts-test": accounts, "event-history-test": hist, "alert-state-test": st}
    ddb = MagicMock()
    ddb.Table.side_effect = lambda name: tables[name]
    return ddb, hist


def _state_of(ddb):
    return ddb.Table("alert-state-test")


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
        ddb, hist = _ddb_with()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist,
            "alert-state-test": MagicMock(**{"get_item.return_value": {}})}[name]

        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["status"] == "ok" and hist.put_item.called


class TestAccountMappingCache:
    def _ddb(self, accounts):
        hist = MagicMock()
        ddb = MagicMock()
        ddb.Table.side_effect = lambda name: {
            "accounts-test": accounts, "event-history-test": hist,
            "alert-state-test": MagicMock(**{"get_item.return_value": {}})}[name]
        return ddb, hist

    def test_mapping_is_scanned_once_per_container(self, env):
        from alert_ingestor import lambda_handler as lh

        accounts = MagicMock()
        accounts.scan.return_value = {"Items": [
            {"account_id": "111122223333", "customer_id": "cust-1"}]}
        ddb, hist = self._ddb(accounts)

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
        ddb, hist = self._ddb(accounts)

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
        ddb, hist = self._ddb(accounts)
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
        ddb, hist = self._ddb(accounts)
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

        assert result["action"] == "notify" and result["state_ok"] is True
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["suppressed"] is False
        assert "suppression_reason" not in item      # 빈 값은 넣지 않는다

    def test_config_change_is_recorded_but_not_actionable(self, env):
        """알람 생성/수정/삭제는 감사용으로 남기되 사람을 깨우지 않고, 상태도 건드리지 않는다."""
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
        assert not _state_of(ddb).get_item.called and not _state_of(ddb).put_item.called

    def test_severity_is_derived_from_metric(self, env):
        """알람 이벤트에는 태그가 없다 — 메트릭 키의 기본 등급을 쓴다."""
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)

        assert hist.put_item.call_args.kwargs["Item"]["severity"].startswith("SEV-")

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

    def test_flapping_policy_from_env(self, env, monkeypatch):
        from alert_ingestor import lambda_handler as lh

        monkeypatch.setenv("ALERT_FLAPPING_QUARANTINE_SEC", "120")
        monkeypatch.setenv("ALERT_FLAPPING_WINDOW_DAYS", "0.5")
        lh._policy.cache_clear()
        p = lh._policy()
        assert p.flapping_quarantine_sec == 120 and p.flapping_window_days == 0.5


class TestStateDecisions:
    """판정 재료는 상태 테이블에서 온다 (design.md D9). 이력은 더 이상 조회하지 않는다."""

    def test_dedup_uses_state_last_notified(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(state_item={
            "state_key": "fp#111122223333#i-0abc#CPUUtilization", "version": 3,
            "last_notified_at": "2026-09-02T10:00:00Z",
            "episode_open": False, "episode_notified": True,
            "recent_episodes": ["2026-09-02T10:00:00Z"],
        })
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)     # 10:15 발생

        assert result["action"] == "suppress" and result["reason"] == "dedup"
        assert not hist.query.called                                    # 이력 스캔 없음
        put = _state_of(ddb).put_item.call_args.kwargs
        assert put["Item"]["version"] == 4 and "ConditionExpression" in put
        assert put["Item"]["last_notified_at"] == "2026-09-02T10:00:00Z"   # dedup은 창을 안 건드린다
        assert put["Item"]["episode_open"] is True                          # 새 에피소드는 열린다

    def test_first_occurrence_creates_state(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify"
        put = _state_of(ddb).put_item.call_args.kwargs
        assert put["Item"]["state_key"] == "fp#111122223333#i-0abc#CPUUtilization"
        assert put["Item"]["version"] == 1
        assert put["Item"]["last_notified_at"] == "2026-09-02T10:15:30Z"
        assert put["Item"]["episode_open"] is True and put["Item"]["episode_notified"] is True
        assert put["Item"]["ttl"] > 0
        assert _state_of(ddb).get_item.call_args.kwargs["ConsistentRead"] is True

    def test_clearing_notifies_only_when_episode_was_notified(self, env):
        from alert_ingestor import lambda_handler as lh

        e = state_change_event()
        e["detail"]["state"]["value"], e["detail"]["previousState"]["value"] = "OK", "ALARM"

        ddb, _ = _ddb_with(state_item={"version": 1, "episode_open": True, "episode_notified": True})
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(e, None)
        assert r["action"] == "notify" and r["reason"] == "cleared"
        assert _state_of(ddb).put_item.call_args.kwargs["Item"]["episode_open"] is False

        ddb, _ = _ddb_with(state_item={"version": 1, "episode_open": True, "episode_notified": False})
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(e, None)
        assert r["action"] == "suppress" and r["reason"] == "cleared"

    def test_flapping_is_quarantined_from_state(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, _ = _ddb_with(state_item={
            "version": 2, "recent_episodes": ["2026-09-02T08:00:00Z", "2026-09-02T09:00:00Z"]})
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)   # 하루 안 3번째

        assert result["reason"] == "flapping" and result["suppressed"] is True
        assert _state_of(ddb).put_item.call_args.kwargs["Item"]["quarantined_until"] \
            == "2026-09-02T11:15:30Z"                                   # 발생 시각 + 1h

    def test_state_read_failure_fails_open_without_writing(self, env):
        """조회 실패 시 첫 발화처럼 알린다 — 그리고 state_ok=False로 드러난다."""
        from alert_ingestor import lambda_handler as lh

        st = MagicMock()
        st.get_item.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetItem")
        ddb, hist = _ddb_with(state=st)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and result["state_ok"] is False
        assert hist.put_item.called and not st.put_item.called

    def test_state_write_other_error_keeps_decision(self, env):
        from alert_ingestor import lambda_handler as lh

        st = MagicMock()
        st.get_item.return_value = {}
        st.put_item.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "PutItem")
        ddb, hist = _ddb_with(state=st)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and result["state_ok"] is False
        assert hist.put_item.called

    def test_write_conflict_rereads_and_dedups(self, env):
        """같은 지문이 동시에 처리되면 진 쪽은 재판정에서 dedup이 된다 — 이중 발송 방지."""
        from alert_ingestor import lambda_handler as lh

        st = MagicMock()
        st.get_item.side_effect = [
            {},                                                            # 1차: 없음
            {"Item": {"version": 1, "last_notified_at": "2026-09-02T10:15:25Z",
                      "episode_open": True, "episode_notified": True,
                      "recent_episodes": ["2026-09-02T10:15:25Z"]}},       # 2차: 남이 방금 알림
        ]
        st.put_item.side_effect = [_conditional_failure(), None]
        ddb, hist = _ddb_with(state=st)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "suppress" and result["reason"] == "dedup"
        assert result["state_ok"] is True
        assert st.get_item.call_count == 2 and st.put_item.call_count == 2
        assert hist.put_item.called

    def test_contention_exhausted_fails_open(self, env):
        from alert_ingestor import lambda_handler as lh

        st = MagicMock()
        st.get_item.return_value = {}
        st.put_item.side_effect = _conditional_failure()
        ddb, hist = _ddb_with(state=st)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and result["reason"] == "state_contention"
        assert result["state_ok"] is False
        assert st.put_item.call_count == lh.STATE_MAX_ATTEMPTS
        assert hist.put_item.called

    def test_state_is_written_before_history(self, env):
        """반대면 이력 뒤 크래시 → 재시도 → 이력 있음 → 상태 영영 미갱신."""
        from alert_ingestor import lambda_handler as lh

        st = MagicMock()
        st.get_item.return_value = {}
        ddb, hist = _ddb_with(state=st)
        order = MagicMock()
        order.attach_mock(st.put_item, "state_put")
        order.attach_mock(hist.put_item, "history_put")
        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)

        assert [c[0] for c in order.mock_calls] == ["state_put", "history_put"]

    def test_missing_state_table_env_decides_stateless(self, env, monkeypatch):
        from alert_ingestor import lambda_handler as lh

        monkeypatch.delenv("ALERT_STATE_TABLE")
        ddb, hist = _ddb_with()
        with patch.object(lh, "_get_ddb", return_value=ddb):
            result = lh.lambda_handler(state_change_event(), None)

        assert result["action"] == "notify" and result["state_ok"] is False
        assert hist.put_item.called


class TestScenarioB1ThroughHandler:
    """review-2026-09-07 B1의 받아들임 기준을 핸들러 + 조건식 해석 가짜 테이블로 재현한다.

    25번 토글 → 발화 NOTIFY 1건. 이전 구현(이력 Query Limit=20)은 ~10번마다 새어 나왔다.
    """

    def test_25_toggles_single_firing_notify(self, env):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(state=fake)
        t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        verdicts = []
        with patch.object(lh, "_get_ddb", return_value=ddb):
            for i in range(25):
                for state, prev, off in (("ALARM", "OK", 0), ("OK", "ALARM", 2)):
                    e = state_change_event(
                        id=f"ev-{i}-{state}",
                        time=(t0 + timedelta(minutes=4 * i + off)).strftime("%Y-%m-%dT%H:%M:%SZ"))
                    e["detail"]["state"]["value"], e["detail"]["previousState"]["value"] = state, prev
                    r = lh.lambda_handler(e, None)
                    verdicts.append((state, r["action"], r["reason"]))

        fired = [v for v in verdicts if v[0] == "ALARM"]
        assert sum(1 for v in fired if v[1] == "notify") == 1
        assert sum(1 for v in fired if v[2] == "flapping") == 23
        assert not any(v[2] == "state_contention" for v in verdicts)
        assert hist.put_item.call_count == 50                    # 이력은 전량
        assert len(fake.items) == 1 and fake.items[next(iter(fake.items))]["version"] == 50
