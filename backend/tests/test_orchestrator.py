"""
Orchestrator Lambda 단위 테스트

검증 범위:
- 계정 목록 로드 (환경변수 정상/오류/미설정)
- Worker Lambda invoke (성공/실패/부분 실패)
- 단일 계정 폴백 동작
"""

import json
import os
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError


# ── 픽스처 ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_lambda_client_cache():
    """각 테스트마다 lru_cache 클라이언트·계정 ID 초기화."""
    from daily_monitor import orchestrator as orch
    for fn in (orch._get_lambda_client, orch._get_ddb, orch._current_account_id):
        fn.cache_clear()
    yield
    for fn in (orch._get_lambda_client, orch._get_ddb, orch._current_account_id):
        fn.cache_clear()


# ── _load_accounts ───────────────────────────────────────────────


def test_load_accounts_returns_accounts_from_env():
    accounts = [
        {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"},
        {"account_id": "222222222222", "role_arn": "arn:aws:iam::222222222222:role/R"},
    ]
    with patch.dict(os.environ, {"MONITORED_ACCOUNTS": json.dumps(accounts)}):
        from daily_monitor.orchestrator import _load_accounts
        result = _load_accounts()
    assert result == accounts


def test_load_accounts_fallback_when_env_not_set():
    with patch.dict(os.environ, {}, clear=False):
        env = {k: v for k, v in os.environ.items() if k != "MONITORED_ACCOUNTS"}
        with patch.dict(os.environ, env, clear=True):
            from daily_monitor.orchestrator import _load_accounts
            result = _load_accounts()
    assert len(result) == 1
    assert result[0]["account_id"] == "self"
    assert result[0]["role_arn"] == ""


def test_load_accounts_returns_empty_on_invalid_json():
    with patch.dict(os.environ, {"MONITORED_ACCOUNTS": "not-valid-json"}):
        from daily_monitor.orchestrator import _load_accounts
        result = _load_accounts()
    assert result == []


def test_load_accounts_returns_empty_when_not_array():
    with patch.dict(os.environ, {"MONITORED_ACCOUNTS": '{"account_id": "123"}'}):
        from daily_monitor.orchestrator import _load_accounts
        result = _load_accounts()
    assert result == []


# ── lambda_handler — 정상 dispatch ──────────────────────────────


def test_lambda_handler_invokes_worker_for_each_account():
    accounts = [
        {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"},
        {"account_id": "222222222222", "role_arn": "arn:aws:iam::222222222222:role/R"},
    ]
    mock_lambda = MagicMock()
    mock_lambda.invoke.return_value = {"StatusCode": 202}

    env = {"MONITORED_ACCOUNTS": json.dumps(accounts), "WORKER_FUNCTION_NAME": "worker-fn"}
    with patch.dict(os.environ, env):
        with patch("daily_monitor.orchestrator._get_lambda_client", return_value=mock_lambda):
            from daily_monitor.orchestrator import lambda_handler
            result = lambda_handler({}, None)

    assert result["status"] == "dispatched"
    assert result["dispatched"] == 2
    assert result["failed"] == 0
    assert mock_lambda.invoke.call_count == 2

    # 각 invoke의 InvocationType이 "Event"(비동기)인지 확인
    for c in mock_lambda.invoke.call_args_list:
        assert c.kwargs["InvocationType"] == "Event"


def test_lambda_handler_passes_account_payload_to_worker():
    account = {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"}
    mock_lambda = MagicMock()
    mock_lambda.invoke.return_value = {"StatusCode": 202}

    env = {"MONITORED_ACCOUNTS": json.dumps([account]), "WORKER_FUNCTION_NAME": "worker-fn"}
    with patch.dict(os.environ, env):
        with patch("daily_monitor.orchestrator._get_lambda_client", return_value=mock_lambda):
            from daily_monitor.orchestrator import lambda_handler
            lambda_handler({}, None)

    payload = json.loads(mock_lambda.invoke.call_args.kwargs["Payload"])
    assert payload["account_id"] == "111111111111"
    assert payload["role_arn"] == "arn:aws:iam::111111111111:role/R"


# ── lambda_handler — 부분 실패 ───────────────────────────────────


def test_lambda_handler_continues_on_partial_invoke_failure():
    accounts = [
        {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"},
        {"account_id": "222222222222", "role_arn": "arn:aws:iam::222222222222:role/R"},
    ]
    mock_lambda = MagicMock()
    # 첫 번째 invoke 실패, 두 번째는 성공
    error_response = {"Error": {"Code": "ResourceNotFoundException", "Message": "fn not found"}}
    mock_lambda.invoke.side_effect = [
        ClientError(error_response, "Invoke"),
        {"StatusCode": 202},
    ]

    env = {"MONITORED_ACCOUNTS": json.dumps(accounts), "WORKER_FUNCTION_NAME": "worker-fn"}
    with patch.dict(os.environ, env):
        with patch("daily_monitor.orchestrator._get_lambda_client", return_value=mock_lambda):
            from daily_monitor.orchestrator import lambda_handler
            result = lambda_handler({}, None)

    assert result["dispatched"] == 1
    assert result["failed"] == 1


def test_lambda_handler_returns_no_accounts_when_list_empty():
    with patch.dict(os.environ, {"MONITORED_ACCOUNTS": "[]", "WORKER_FUNCTION_NAME": "fn"}):
        with patch("daily_monitor.orchestrator._get_lambda_client"):
            from daily_monitor.orchestrator import lambda_handler
            # 빈 배열이면 단일 계정 폴백이 아닌 no_accounts 반환
            # (명시적으로 빈 배열을 준 경우는 운영자 의도로 간주)
            # _load_accounts가 [] 반환 → lambda_handler가 no_accounts 반환
            # 단, 빈 배열도 폴백하는 게 맞는지 비즈니스 결정 필요
            # 현재 구현: 빈 배열 → "no_accounts"
            result = lambda_handler({}, None)
    # MONITORED_ACCOUNTS=[] → _load_accounts returns [] → no_accounts
    assert result["status"] == "no_accounts"


# ──────────────────────────────────────────────
# 2026-09-23 — 등록된 계정 표가 정본.
# 그 전까지 이 모듈은 MONITORED_ACCOUNTS만 봤고 템플릿이 빈 문자열을 줘서 **항상** 현재 계정 하나로
# 폴백했다. 고객사 계정을 등록해도 데일리 런이 그 계정을 건드리지 않았고, 알림 전달은 별도 경로라
# 정상 동작해서 "알람 생성만 안 된다"로 보였다. 첫 실고객 온보딩에서 드러남.
# ──────────────────────────────────────────────

TABLE_ENV = {"ACCOUNTS_TABLE": "accounts-test", "WORKER_FUNCTION_NAME": "fn"}


def _table(*pages):
    """종료 페이지를 반드시 준다 — bare MagicMock이면 LastEvaluatedKey가 truthy라 루프가 안 끝난다(AP-15)."""
    table = MagicMock()
    table.scan.side_effect = list(pages)
    ddb = MagicMock()
    ddb.Table.return_value = table
    return ddb, table


def _load_with(ddb, *, me="949501913924", env=None):
    from daily_monitor import orchestrator as orch
    merged = {**TABLE_ENV, **(env or {})}
    clean = {k: v for k, v in os.environ.items() if k != "MONITORED_ACCOUNTS"}
    with patch.dict(os.environ, {**clean, **merged}, clear=True), \
         patch.object(orch, "_get_ddb", return_value=ddb), \
         patch.object(orch, "_current_account_id", return_value=me):
        return orch._load_accounts()


class TestAccountsComeFromTheRegistrationTable:
    def test_registered_accounts_are_dispatched(self):
        ddb, _ = _table({"Items": [
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/AlarmManagerMonitoringRole"}]})
        assert _load_with(ddb) == [
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/AlarmManagerMonitoringRole"}]

    def test_our_own_account_is_dispatched_without_a_role_to_assume(self):
        """표의 role_arn은 앱이 읽기용으로 쓰는 값이다 — 워커가 그걸로 자기 계정에 AssumeRole 하면 실패한다."""
        ddb, _ = _table({"Items": [
            {"account_id": "949501913924", "role_arn": "arn:aws:iam::949501913924:role/some-api-role"}]})
        assert _load_with(ddb) == [{"account_id": "949501913924", "role_arn": ""}]

    def test_one_account_under_two_customers_runs_once(self):
        """계정 표의 키가 customer_id + account_id라 같은 계정이 여러 행일 수 있다."""
        ddb, _ = _table({"Items": [
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/R"},
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/R"},
            {"account_id": "222233334444", "role_arn": "arn:aws:iam::222233334444:role/R"}]})
        assert [a["account_id"] for a in _load_with(ddb)] == ["771283576189", "222233334444"]

    def test_every_page_is_read(self):
        ddb, table = _table(
            {"Items": [{"account_id": "111111111111", "role_arn": "a"}], "LastEvaluatedKey": {"k": 1}},
            {"Items": [{"account_id": "222222222222", "role_arn": "b"}]})
        assert [a["account_id"] for a in _load_with(ddb)] == ["111111111111", "222222222222"]
        assert table.scan.call_count == 2
        assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"k": 1}

    def test_rows_without_an_account_id_are_skipped(self):
        ddb, _ = _table({"Items": [{"role_arn": "orphan"}, {"account_id": "  "},
                                   {"account_id": "333344445555", "role_arn": "r"}]})
        assert [a["account_id"] for a in _load_with(ddb)] == ["333344445555"]

    def test_empty_table_falls_back_to_the_current_account(self):
        ddb, _ = _table({"Items": []})
        assert _load_with(ddb) == [{"account_id": "self", "role_arn": ""}]

    def test_unreadable_table_falls_back_instead_of_running_nothing(self):
        """표를 못 읽는다고 0건을 돌리면 그날 모니터링이 통째로 조용히 사라진다."""
        from daily_monitor import orchestrator as orch
        ddb = MagicMock()
        ddb.Table.return_value.scan.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Scan")
        assert _load_with(ddb) == [{"account_id": "self", "role_arn": ""}]

    def test_env_override_still_wins(self):
        """비상용 수동 지정 — 표를 읽지 않는다."""
        from daily_monitor import orchestrator as orch
        ddb, table = _table({"Items": [{"account_id": "771283576189", "role_arn": "r"}]})
        manual = [{"account_id": "999988887777", "role_arn": "manual"}]
        with patch.dict(os.environ, {**TABLE_ENV, "MONITORED_ACCOUNTS": json.dumps(manual)}), \
             patch.object(orch, "_get_ddb", return_value=ddb):
            assert orch._load_accounts() == manual
        table.scan.assert_not_called()

    def test_the_worker_receives_one_invoke_per_registered_account(self):
        from daily_monitor import orchestrator as orch
        ddb, _ = _table({"Items": [
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/R"},
            {"account_id": "949501913924", "role_arn": "arn:aws:iam::949501913924:role/ignored"}]})
        lam = MagicMock()
        clean = {k: v for k, v in os.environ.items() if k != "MONITORED_ACCOUNTS"}
        with patch.dict(os.environ, {**clean, **TABLE_ENV}, clear=True), \
             patch.object(orch, "_get_ddb", return_value=ddb), \
             patch.object(orch, "_current_account_id", return_value="949501913924"), \
             patch.object(orch, "_get_lambda_client", return_value=lam):
            result = orch.lambda_handler({}, None)
        assert result["status"] == "dispatched" and result["dispatched"] == 2
        sent = [json.loads(c.kwargs["Payload"]) for c in lam.invoke.call_args_list]
        assert sent == [
            {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/R"},
            {"account_id": "949501913924", "role_arn": ""}]

    def test_mode_is_passed_through_to_every_account(self):
        """시간 단위 태그 정합 런도 같은 팬아웃을 쓴다."""
        from daily_monitor import orchestrator as orch
        ddb, _ = _table({"Items": [{"account_id": "771283576189", "role_arn": "r"}]})
        lam = MagicMock()
        clean = {k: v for k, v in os.environ.items() if k != "MONITORED_ACCOUNTS"}
        with patch.dict(os.environ, {**clean, **TABLE_ENV}, clear=True), \
             patch.object(orch, "_get_ddb", return_value=ddb), \
             patch.object(orch, "_current_account_id", return_value="949501913924"), \
             patch.object(orch, "_get_lambda_client", return_value=lam):
            orch.lambda_handler({"mode": "tag_reconcile"}, None)
        assert json.loads(lam.invoke.call_args.kwargs["Payload"])["mode"] == "tag_reconcile"

    def test_scan_only_reads_the_two_fields_it_needs(self):
        ddb, table = _table({"Items": []})
        _load_with(ddb)
        assert table.scan.call_args.kwargs["ProjectionExpression"] == "account_id, role_arn"


class TestOrchestratorTemplateWiring:
    """코드가 표를 읽어도 함수에 env가 없거나 롤에 권한이 없으면 조용히 폴백한다(AP-19와 같은 짝)."""

    @staticmethod
    def _template():
        import pathlib
        import yaml

        class Loader(yaml.SafeLoader):
            pass

        def any_tag(loader, suffix, node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        Loader.add_multi_constructor("!", any_tag)
        root = pathlib.Path(__file__).resolve().parents[2]
        return yaml.load((root / "infrastructure/backend/template.yaml").read_text(encoding="utf-8"), Loader=Loader)

    def test_orchestrator_knows_the_accounts_table(self):
        env = self._template()["Resources"]["OrchestratorFunction"]["Properties"]["Environment"]["Variables"]
        assert env.get("ACCOUNTS_TABLE") == "AccountsTable"

    def test_orchestrator_may_read_the_accounts_table(self):
        role = self._template()["Resources"]["OrchestratorRole"]["Properties"]["Policies"][0]
        actions = []
        for st in role["PolicyDocument"]["Statement"]:
            a = st.get("Action")
            actions.extend(a if isinstance(a, list) else [a])
        assert "dynamodb:Scan" in actions
