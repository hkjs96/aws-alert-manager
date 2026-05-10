"""
Severity 등급 단위 테스트 (TDD Red 단계)

검증 범위:
- get_severity(): 메트릭 키 → SEV-1~5 매핑
- get_severity(): 미정의 메트릭 → SEV-5 폴백
- get_severity(): Disk_ prefix 처리
- _tag_alarm_with_severity(): tag_resource 호출 파라미터
- _tag_alarm_with_severity(): tag_resource 실패 시 예외 미전파
- alarm_builder: put_metric_alarm 성공 후 severity 태그 부여
"""

from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError


# ── get_severity ─────────────────────────────────────────────────


def test_get_severity_sev1_metrics():
    from common.alarm_registry import get_severity
    for metric in ("StatusCheckFailed", "HealthyHostCount", "TunnelState",
                   "ConnectionState", "HealthCheckStatus", "ActiveControllerCount"):
        assert get_severity(metric) == "SEV-1", f"{metric} should be SEV-1"


def test_get_severity_sev2_metrics():
    from common.alarm_registry import get_severity
    for metric in ("ELB5XX", "Errors", "UnHealthyHostCount",
                   "Api5XXError", "Api5xx", "ErrorPortAllocation", "TargetConnectionError"):
        assert get_severity(metric) == "SEV-2", f"{metric} should be SEV-2"


def test_get_severity_sev3_metrics():
    from common.alarm_registry import get_severity
    for metric in ("CPU", "Memory", "FreeMemoryGB", "FreeStorageGB",
                   "FreeLocalStorageGB", "EngineCPU", "ACUUtilization",
                   "DaysToExpiry", "ReplicaLag"):
        assert get_severity(metric) == "SEV-3", f"{metric} should be SEV-3"


def test_get_severity_sev4_metrics():
    from common.alarm_registry import get_severity
    for metric in ("ReadLatency", "WriteLatency", "TargetResponseTime",
                   "TGResponseTime", "Duration", "ApiLatency"):
        assert get_severity(metric) == "SEV-4", f"{metric} should be SEV-4"


def test_get_severity_sev5_metrics():
    from common.alarm_registry import get_severity
    for metric in ("RequestCount", "Connections", "ProcessedBytes",
                   "ActiveFlowCount", "NewFlowCount", "ConnectionAttempts"):
        assert get_severity(metric) == "SEV-5", f"{metric} should be SEV-5"


def test_get_severity_unknown_metric_falls_back_to_sev5():
    from common.alarm_registry import get_severity
    assert get_severity("SomeUnknownMetric") == "SEV-5"
    assert get_severity("") == "SEV-5"


def test_get_severity_disk_prefix_is_sev3():
    """Disk_root, Disk_data 등 prefix 형태는 SEV-3 (포화도)."""
    from common.alarm_registry import get_severity
    assert get_severity("Disk_root") == "SEV-3"
    assert get_severity("Disk_data") == "SEV-3"
    assert get_severity("Disk_var_log") == "SEV-3"


# ── _tag_alarm_with_severity ─────────────────────────────────────


def test_tag_alarm_calls_tag_resource_with_correct_params():
    mock_cw = MagicMock()
    mock_cw.meta.region_name = "ap-northeast-2"

    with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"):
        from common.alarm_builder import _tag_alarm_with_severity
        _tag_alarm_with_severity("my-alarm", "CPU", mock_cw)

    mock_cw.tag_resource.assert_called_once_with(
        ResourceARN="arn:aws:cloudwatch:ap-northeast-2:123456789012:alarm:my-alarm",
        Tags=[
            {"Key": "Severity", "Value": "SEV-3"},
            {"Key": "ManagedBy", "Value": "AlarmManager"},
        ],
    )


def test_tag_alarm_does_not_raise_on_tag_resource_failure():
    """tag_resource 실패가 알람 생성 흐름을 중단하지 않아야 한다."""
    mock_cw = MagicMock()
    mock_cw.meta.region_name = "ap-northeast-2"
    mock_cw.tag_resource.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "TagResource"
    )

    with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"):
        from common.alarm_builder import _tag_alarm_with_severity
        # 예외가 전파되지 않아야 한다
        _tag_alarm_with_severity("my-alarm", "StatusCheckFailed", mock_cw)


def test_tag_alarm_uses_sev1_for_status_check_failed():
    mock_cw = MagicMock()
    mock_cw.meta.region_name = "ap-northeast-2"

    with patch("common.alarm_builder._get_aws_account_id", return_value="000000000000"):
        from common.alarm_builder import _tag_alarm_with_severity
        _tag_alarm_with_severity("alarm-name", "StatusCheckFailed", mock_cw)

    tags = mock_cw.tag_resource.call_args.kwargs["Tags"]
    severity_tag = next(t for t in tags if t["Key"] == "Severity")
    assert severity_tag["Value"] == "SEV-1"


# ── _create_standard_alarm: severity 태그 부여 통합 ──────────────


def test_create_standard_alarm_tags_severity_after_put():
    """put_metric_alarm 성공 후 tag_resource가 호출되어야 한다."""
    mock_cw = MagicMock()
    mock_cw.meta.region_name = "ap-northeast-2"

    alarm_def = {
        "metric": "CPU",
        "metric_name": "CPUUtilization",
        "namespace": "AWS/EC2",
        "stat": "Average",
        "period": 300,
        "evaluation_periods": 2,
        "comparison": "GreaterThanThreshold",
        "treat_missing_data": "missing",
        "threshold": 80,
    }

    with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"):
        with patch("common.alarm_builder._build_dimensions", return_value=[{"Name": "InstanceId", "Value": "i-abc"}]):
            with patch("common.alarm_builder.resolve_threshold", return_value=(80, 80.0)):
                with patch("common.alarm_builder._get_sns_alert_arn", return_value=""):
                    from common.alarm_builder import _create_standard_alarm
                    result = _create_standard_alarm(alarm_def, "i-abc", "EC2", {"Name": "test"}, mock_cw)

    assert result is not None
    mock_cw.put_metric_alarm.assert_called_once()
    mock_cw.tag_resource.assert_called_once()
    tags = mock_cw.tag_resource.call_args.kwargs["Tags"]
    assert any(t["Key"] == "Severity" and t["Value"] == "SEV-3" for t in tags)
    assert any(t["Key"] == "ManagedBy" and t["Value"] == "AlarmManager" for t in tags)


def test_create_standard_alarm_does_not_tag_when_put_fails():
    """put_metric_alarm 실패 시 tag_resource를 호출하지 않는다."""
    mock_cw = MagicMock()
    mock_cw.meta.region_name = "ap-northeast-2"
    mock_cw.put_metric_alarm.side_effect = ClientError(
        {"Error": {"Code": "LimitExceeded", "Message": "limit"}}, "PutMetricAlarm"
    )

    alarm_def = {
        "metric": "CPU", "metric_name": "CPUUtilization", "namespace": "AWS/EC2",
        "stat": "Average", "period": 300, "evaluation_periods": 2,
        "comparison": "GreaterThanThreshold", "treat_missing_data": "missing",
        "threshold": 80,
    }

    with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"):
        with patch("common.alarm_builder._build_dimensions", return_value=[]):
            with patch("common.alarm_builder.resolve_threshold", return_value=(80, 80.0)):
                with patch("common.alarm_builder._get_sns_alert_arn", return_value=""):
                    from common.alarm_builder import _create_standard_alarm
                    result = _create_standard_alarm(alarm_def, "i-abc", "EC2", {}, mock_cw)

    assert result is None
    mock_cw.tag_resource.assert_not_called()
