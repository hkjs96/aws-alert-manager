"""
alarm_manager 단위 테스트

CloudWatch Alarm 자동 생성/삭제/동기화 기능 검증.
"""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from common.alarm_manager import (
    _alarm_name,
    _extract_elb_dimension,
    _get_alarm_defs,
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    import common.alarm_manager as am
    am._cw_client = None
    yield
    am._cw_client = None


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")


# ──────────────────────────────────────────────
# _alarm_name / _extract_elb_dimension
# ──────────────────────────────────────────────

class TestHelpers:

    def test_alarm_name_format(self):
        assert _alarm_name("i-001", "CPU") == "i-001-CPU-prod"

    def test_alarm_name_with_different_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "dev")
        assert _alarm_name("db-001", "FreeMemoryGB") == "db-001-FreeMemoryGB-dev"

    def test_extract_elb_dimension_from_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        assert _extract_elb_dimension(arn) == "app/my-alb/abc123"

    def test_extract_elb_dimension_fallback(self):
        assert _extract_elb_dimension("not-an-arn") == "not-an-arn"

    def test_get_alarm_defs_ec2(self):
        defs = _get_alarm_defs("EC2")
        assert len(defs) == 1
        assert defs[0]["metric"] == "CPU"

    def test_get_alarm_defs_rds(self):
        defs = _get_alarm_defs("RDS")
        assert len(defs) == 4
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections"}

    def test_get_alarm_defs_elb(self):
        defs = _get_alarm_defs("ELB")
        assert len(defs) == 1
        assert defs[0]["metric"] == "RequestCount"

    def test_get_alarm_defs_unknown(self):
        assert _get_alarm_defs("UNKNOWN") == []


# ──────────────────────────────────────────────
# create_alarms_for_resource
# ──────────────────────────────────────────────

class TestCreateAlarms:

    def test_ec2_creates_cpu_alarm(self):
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {"Monitoring": "on"})

        assert created == ["i-001-CPU-prod"]
        mock_cw.put_metric_alarm.assert_called_once()
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["AlarmName"] == "i-001-CPU-prod"
        assert kwargs["Namespace"] == "AWS/EC2"
        assert kwargs["MetricName"] == "CPUUtilization"
        assert kwargs["Threshold"] == 80.0  # default

    def test_ec2_custom_threshold_from_tag(self):
        mock_cw = MagicMock()
        tags = {"Monitoring": "on", "Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", tags)

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["Threshold"] == 90.0

    def test_rds_creates_four_alarms(self):
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", {"Monitoring": "on"})

        assert len(created) == 4
        assert mock_cw.put_metric_alarm.call_count == 4

    def test_rds_free_memory_threshold_converted_to_bytes(self):
        mock_cw = MagicMock()
        tags = {"Monitoring": "on", "Threshold_FreeMemoryGB": "4"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("db-001", "RDS", tags)

        # FreeMemoryGB alarm call
        calls = mock_cw.put_metric_alarm.call_args_list
        free_mem_call = [c for c in calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        # 4 GB = 4 * 1024^3 bytes
        assert free_mem_call.kwargs["Threshold"] == 4 * 1024 * 1024 * 1024

    def test_elb_extracts_dimension_from_arn(self):
        mock_cw = MagicMock()
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(arn, "ELB", {"Monitoring": "on"})

        assert len(created) == 1
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        dims = kwargs["Dimensions"]
        assert dims[0]["Value"] == "app/my-alb/abc"

    def test_sns_arn_set_as_alarm_action(self):
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["AlarmActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]
        assert kwargs["OKActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]

    def test_no_sns_arn_empty_actions(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "")
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["AlarmActions"] == []

    def test_client_error_logged_and_skipped(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "LimitExceeded", "Message": "too many"}}, "PutMetricAlarm"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        assert created == []

    def test_unknown_resource_type_returns_empty(self):
        created = create_alarms_for_resource("x-001", "UNKNOWN", {})
        assert created == []


# ──────────────────────────────────────────────
# delete_alarms_for_resource
# ──────────────────────────────────────────────

class TestDeleteAlarms:

    def test_ec2_deletes_one_alarm(self):
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert deleted == ["i-001-CPU-prod"]
        mock_cw.delete_alarms.assert_called_once_with(AlarmNames=["i-001-CPU-prod"])

    def test_rds_deletes_four_alarms(self):
        mock_cw = MagicMock()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("db-001", "RDS")

        assert len(deleted) == 4
        mock_cw.delete_alarms.assert_called_once()

    def test_unknown_type_returns_empty(self):
        deleted = delete_alarms_for_resource("x-001", "UNKNOWN")
        assert deleted == []

    def test_client_error_returns_empty(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.delete_alarms.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFound", "Message": "nope"}}, "DeleteAlarms"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert deleted == []


# ──────────────────────────────────────────────
# sync_alarms_for_resource
# ──────────────────────────────────────────────

class TestSyncAlarms:

    def test_missing_alarm_gets_created(self):
        mock_cw = MagicMock()
        mock_cw.describe_alarms.return_value = {"MetricAlarms": []}
        mock_cw.put_metric_alarm.return_value = {}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert "i-001-CPU-prod" in result["created"]
        assert result["updated"] == []

    def test_matching_threshold_is_ok(self):
        mock_cw = MagicMock()
        mock_cw.describe_alarms.return_value = {
            "MetricAlarms": [{"Threshold": 80.0}]
        }
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert result["ok"] == ["i-001-CPU-prod"]
        assert result["created"] == []
        assert result["updated"] == []

    def test_mismatched_threshold_gets_updated(self):
        mock_cw = MagicMock()
        mock_cw.describe_alarms.return_value = {
            "MetricAlarms": [{"Threshold": 70.0}]
        }
        mock_cw.put_metric_alarm.return_value = {}
        tags = {"Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert "i-001-CPU-prod" in result["updated"]
