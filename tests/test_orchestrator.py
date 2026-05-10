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
    """각 테스트마다 lru_cache 클라이언트 초기화."""
    from daily_monitor.orchestrator import _get_lambda_client
    _get_lambda_client.cache_clear()
    yield
    _get_lambda_client.cache_clear()


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
