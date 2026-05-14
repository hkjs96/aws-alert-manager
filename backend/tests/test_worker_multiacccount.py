"""
Worker Lambda 멀티 어카운트 세션 전환 테스트

검증 범위:
- role_arn 없을 때 AssumeRole 미호출 (단일 계정 모드)
- role_arn 있을 때 AssumeRole 호출 + setup_default_session 적용
- AssumeRole 실패 시 즉시 에러 반환 (처리 미진행)
- lru_cache 클라이언트 무효화 확인
- account_id가 결과에 포함되는지 확인
"""

from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError


FAKE_CREDS = {
    "AccessKeyId": "ASIAFAKE",
    "SecretAccessKey": "fakesecret",
    "SessionToken": "faketoken",
}


# ── _switch_account_session ──────────────────────────────────────


def test_switch_account_session_calls_assume_role():
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": FAKE_CREDS}

    with patch("boto3.client", return_value=mock_sts) as mock_boto:
        with patch("boto3.setup_default_session") as mock_session:
            with patch("daily_monitor.lambda_handler._clear_all_client_caches") as mock_clear:
                from daily_monitor.lambda_handler import _switch_account_session
                _switch_account_session("arn:aws:iam::111:role/R", "111")

    mock_sts.assume_role.assert_called_once_with(
        RoleArn="arn:aws:iam::111:role/R",
        RoleSessionName="DailyMonitor-111",
    )
    mock_session.assert_called_once_with(
        aws_access_key_id=FAKE_CREDS["AccessKeyId"],
        aws_secret_access_key=FAKE_CREDS["SecretAccessKey"],
        aws_session_token=FAKE_CREDS["SessionToken"],
    )
    mock_clear.assert_called_once()


def test_switch_account_session_raises_on_assume_role_failure():
    mock_sts = MagicMock()
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not allowed"}}, "AssumeRole"
    )
    mock_sts.assume_role.side_effect = error

    with patch("boto3.client", return_value=mock_sts):
        with patch("boto3.setup_default_session"):
            from daily_monitor.lambda_handler import _switch_account_session
            with pytest.raises(ClientError):
                _switch_account_session("arn:aws:iam::111:role/R", "111")


# ── _clear_all_client_caches ─────────────────────────────────────


def test_clear_all_client_caches_clears_handler_client():
    """핸들러 자체의 _get_cw_client lru_cache가 무효화되는지 확인."""
    from daily_monitor import lambda_handler as lh
    # 캐시에 값을 채움
    with patch("boto3.client", return_value=MagicMock()):
        lh._get_cw_client()

    cache_info_before = lh._get_cw_client.cache_info()
    assert cache_info_before.currsize == 1

    lh._clear_all_client_caches()

    cache_info_after = lh._get_cw_client.cache_info()
    assert cache_info_after.currsize == 0


# ── lambda_handler — 단일 계정 모드 ─────────────────────────────


def test_lambda_handler_skips_assume_role_when_no_role_arn():
    """event에 role_arn 없으면 AssumeRole 미호출."""
    with patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch:
        with patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]):
            with patch("daily_monitor.lambda_handler._COLLECTOR_MODULES", []):
                from daily_monitor.lambda_handler import lambda_handler
                result = lambda_handler({}, None)

    mock_switch.assert_not_called()
    assert result["status"] == "ok"
    assert result["account_id"] == "self"


def test_lambda_handler_skips_assume_role_when_role_arn_empty():
    """role_arn이 빈 문자열이면 AssumeRole 미호출."""
    with patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch:
        with patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]):
            with patch("daily_monitor.lambda_handler._COLLECTOR_MODULES", []):
                from daily_monitor.lambda_handler import lambda_handler
                result = lambda_handler({"account_id": "self", "role_arn": ""}, None)

    mock_switch.assert_not_called()
    assert result["account_id"] == "self"


# ── lambda_handler — 멀티 어카운트 모드 ─────────────────────────


def test_lambda_handler_calls_switch_session_with_role_arn():
    """role_arn이 있으면 _switch_account_session 호출."""
    event = {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"}

    with patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch:
        with patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]):
            with patch("daily_monitor.lambda_handler._COLLECTOR_MODULES", []):
                from daily_monitor.lambda_handler import lambda_handler
                result = lambda_handler(event, None)

    mock_switch.assert_called_once_with("arn:aws:iam::111111111111:role/R", "111111111111")
    assert result["account_id"] == "111111111111"


def test_lambda_handler_returns_error_on_assume_role_failure():
    """AssumeRole 실패 시 즉시 에러 반환, 리소스 처리 미진행."""
    event = {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/R"}
    error = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "AssumeRole")

    with patch("daily_monitor.lambda_handler._switch_account_session", side_effect=error):
        with patch("daily_monitor.lambda_handler._cleanup_orphan_alarms") as mock_cleanup:
            from daily_monitor.lambda_handler import lambda_handler
            result = lambda_handler(event, None)

    assert result["status"] == "error"
    assert result["account_id"] == "111111111111"
    assert result["reason"] == "assume_role_failed"
    # AssumeRole 실패 후 리소스 처리 미진행
    mock_cleanup.assert_not_called()


def test_lambda_handler_includes_account_id_in_success_result():
    """성공 응답에 account_id 포함."""
    event = {"account_id": "222222222222", "role_arn": "arn:aws:iam::222222222222:role/R"}

    with patch("daily_monitor.lambda_handler._switch_account_session"):
        with patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]):
            with patch("daily_monitor.lambda_handler._COLLECTOR_MODULES", []):
                from daily_monitor.lambda_handler import lambda_handler
                result = lambda_handler(event, None)

    assert result["status"] == "ok"
    assert result["account_id"] == "222222222222"
