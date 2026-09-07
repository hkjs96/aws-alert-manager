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

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from common.alarm_naming import _build_alarm_description
from fakes_ddb import FakeSfn, FakeStateTable, conditional_failure as _conditional_failure
from tests.test_alert_event import state_change_event

SM_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:aws-monitoring-alert-group-test"
ACCOUNTS = [{"account_id": "111122223333", "customer_id": "cust-1"}]


@pytest.fixture(autouse=True)
def _reset_caches():
    from alert_ingestor import lambda_handler as lh
    lh._get_ddb.cache_clear()
    lh._get_sfn.cache_clear()
    lh._reset_account_cache()
    lh._policy.cache_clear()
    yield
    lh._get_ddb.cache_clear()
    lh._get_sfn.cache_clear()
    lh._reset_account_cache()
    lh._policy.cache_clear()


@pytest.fixture
def env(monkeypatch):
    """그룹은 꺼진 상태(상태 머신 ARN 없음) — 그룹 테스트는 `grouping` 픽스처를 쓴다."""
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "event-history-test")
    monkeypatch.setenv("ACCOUNTS_TABLE", "accounts-test")
    monkeypatch.setenv("ALERT_STATE_TABLE", "alert-state-test")
    monkeypatch.delenv("ALERT_GROUP_STATE_MACHINE_ARN", raising=False)


@pytest.fixture
def grouping(env, monkeypatch):
    """그룹 켜짐: 상태 머신 ARN + 가짜 Step Functions."""
    monkeypatch.setenv("ALERT_GROUP_STATE_MACHINE_ARN", SM_ARN)
    monkeypatch.setenv("ALERT_GROUP_WAIT_SEC", "30")
    from alert_ingestor import lambda_handler as lh
    lh._policy.cache_clear()
    sfn = FakeSfn()
    with patch.object(lh, "_get_sfn", return_value=sfn):
        yield sfn


def _series_event(i: int, **over):
    """서로 다른 리소스(= 서로 다른 지문)의 발화 이벤트."""
    e = state_change_event(id=f"ev-{i}", **over)
    e["detail"]["alarmName"] = f"[EC2] web-{i} CPUUtilization > 80% (TagName: i-{i:04d})"
    e["detail"]["configuration"]["description"] = _build_alarm_description(
        "EC2", f"i-{i:04d}", "CPUUtilization", "auto")
    return e


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


class TestGrouping:
    """실행은 그룹당 하나 (design.md D10). 구성원 자격은 적재 시 이력의 group_id로 정한다."""

    def test_first_notify_opens_group_and_starts_execution(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(state_change_event(), None)

        assert r["action"] == "notify" and r["group_ok"] is True
        assert len(grouping.calls) == 1
        call = grouping.calls[0]
        assert call["name"] == r["group_id"]
        assert re.fullmatch(r"g-[0-9a-f]{16}-\d{14}", call["name"])
        assert call["stateMachineArn"] == SM_ARN
        item = hist.put_item.call_args.kwargs["Item"]
        assert item["group_id"] == call["name"]
        assert call["input"]["group_key"] == f"cust-1#{item['severity']}"
        assert call["input"]["customer_id"] == "cust-1" and call["input"]["group_wait_sec"] == 30

        grp = fake.by_prefix("grp#")
        assert len(grp) == 1
        g = next(iter(grp.values()))
        assert g["status"] == "open" and g["group_id"] == call["name"]
        assert g["execution_arn"].endswith(":" + call["name"]) and g["version"] == 2

    def test_later_events_join_without_new_execution(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            results = [lh.lambda_handler(_series_event(i), None) for i in range(3)]

        assert len(grouping.calls) == 1
        assert {r["group_id"] for r in results} == {grouping.calls[0]["name"]}
        assert all(r["group_ok"] for r in results)
        assert len(fake.by_prefix("fp#")) == 3 and len(fake.by_prefix("grp#")) == 1

    def test_suppressed_event_is_not_grouped(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        fake.items["fp#111122223333#i-0abc#CPUUtilization"] = {
            "state_key": "fp#111122223333#i-0abc#CPUUtilization", "version": 1,
            "last_notified_at": "2026-09-02T10:10:00Z", "episode_open": False,
            "recent_episodes": ["2026-09-02T10:10:00Z"]}
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(state_change_event(), None)

        assert r["reason"] == "dedup" and r["group_id"] == ""
        assert not grouping.calls and not fake.by_prefix("grp#")
        assert "group_id" not in hist.put_item.call_args.kwargs["Item"]

    def test_clearing_notify_is_grouped(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        fake.items["fp#111122223333#i-0abc#CPUUtilization"] = {
            "state_key": "fp#111122223333#i-0abc#CPUUtilization", "version": 1,
            "episode_open": True, "episode_notified": True}
        e = state_change_event()
        e["detail"]["state"]["value"], e["detail"]["previousState"]["value"] = "OK", "ALARM"
        ddb, _ = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(e, None)

        assert r["reason"] == "cleared" and r["action"] == "notify"
        assert len(grouping.calls) == 1 and r["group_id"] == grouping.calls[0]["name"]

    def test_open_group_without_execution_is_restarted(self, grouping):
        """연 쪽이 StartExecution 전에 죽었다 — 다음 이벤트가 같은 이름으로 시작한다."""
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            first = lh.lambda_handler(_series_event(1), None)
            gk = [k for k in fake.items if k.startswith("grp#")][0]
            fake.items[gk].pop("execution_arn")                  # 죽은 척
            second = lh.lambda_handler(_series_event(2), None)

        assert second["group_id"] == first["group_id"] and second["group_ok"] is True
        # 두 번째 시도는 같은 이름 → ExecutionAlreadyExists → 성공으로 처리
        assert len(grouping.calls) == 1
        assert fake.items[gk]["execution_arn"].endswith(":" + first["group_id"])

    def test_start_execution_failure_fails_open(self, grouping):
        from alert_ingestor import lambda_handler as lh

        grouping.fail_with = "AccessDeniedException"
        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(state_change_event(), None)

        assert r["action"] == "notify" and r["group_ok"] is False
        assert r["group_id"]                                      # 그룹은 열렸다 — 다음 이벤트가 재시작
        g = next(iter(fake.by_prefix("grp#").values()))
        assert g["status"] == "open" and "execution_arn" not in g
        assert hist.put_item.call_args.kwargs["Item"]["group_id"] == r["group_id"]

    def test_closed_group_reopens_with_new_id(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            first = lh.lambda_handler(_series_event(1), None)
            gk = [k for k in fake.items if k.startswith("grp#")][0]
            fake.items[gk]["status"] = "closed"                  # 워커가 닫은 척 (group_id는 진짜 이름 그대로)
            second = lh.lambda_handler(_series_event(2), None)

        # 같은 초에 다시 열려도 이름이 겹치지 않는다 — 겹치면 옛 실행에 조용히 붙는다
        assert second["group_id"] != first["group_id"] and second["group_ok"] is True
        assert fake.items[gk]["status"] == "open" and fake.items[gk]["version"] == 4
        assert fake.items[gk]["group_id"] == second["group_id"]
        assert len(grouping.calls) == 2

    def test_grouping_disabled_without_state_machine_env(self, env):
        from alert_ingestor import lambda_handler as lh

        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=FakeStateTable())
        with patch.object(lh, "_get_ddb", return_value=ddb):
            r = lh.lambda_handler(state_change_event(), None)

        assert r["action"] == "notify" and r["group_ok"] is False and r["group_id"] == ""
        assert "group_id" not in hist.put_item.call_args.kwargs["Item"]

    def test_state_then_group_then_history_order(self, grouping):
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        spy = MagicMock(wraps=fake)
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=spy)
        order = MagicMock()
        order.attach_mock(spy.put_item, "state_put")
        order.attach_mock(hist.put_item, "history_put")
        with patch.object(lh, "_get_ddb", return_value=ddb):
            lh.lambda_handler(state_change_event(), None)

        names = [c[0] for c in order.mock_calls]
        assert names == ["state_put", "state_put", "state_put", "history_put"]     # fp#, grp# 열기, arn, 이력
        assert order.mock_calls[0].kwargs["Item"]["state_key"].startswith("fp#")

    def test_storm_500_events_one_execution(self, grouping):
        """받아들임 기준: 같은 고객사·등급으로 500건 → 실행 1개, 이력 전부 같은 group_id."""
        from alert_ingestor import lambda_handler as lh

        fake = FakeStateTable()
        ddb, hist = _ddb_with(accounts_items=ACCOUNTS, state=fake)
        t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        with patch.object(lh, "_get_ddb", return_value=ddb):
            results = [
                lh.lambda_handler(_series_event(
                    i, time=(t0 + timedelta(milliseconds=120 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")), None)
                for i in range(500)
            ]

        assert len(grouping.calls) == 1
        gid = grouping.calls[0]["name"]
        assert all(r["action"] == "notify" and r["group_ok"] for r in results)
        assert {c.kwargs["Item"]["group_id"] for c in hist.put_item.call_args_list} == {gid}
        assert len(fake.by_prefix("fp#")) == 500 and len(fake.by_prefix("grp#")) == 1
