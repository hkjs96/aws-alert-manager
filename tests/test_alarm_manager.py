"""
alarm_manager 단위 테스트

CloudWatch Alarm 자동 생성/삭제/동기화 기능 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from common.alarm_manager import (
    _alarm_name,
    _extract_elb_dimension,
    _get_alarm_defs,
    _pretty_alarm_name,
    _find_alarms_for_resource,
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
# Helper 함수 테스트
# ──────────────────────────────────────────────

class TestHelpers:

    def test_legacy_alarm_name_format(self):
        assert _alarm_name("i-001", "CPU") == "i-001-CPU-prod"

    def test_legacy_alarm_name_with_different_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "dev")
        assert _alarm_name("db-001", "FreeMemoryGB") == "db-001-FreeMemoryGB-dev"

    def test_pretty_alarm_name_ec2_cpu(self):
        name = _pretty_alarm_name("EC2", "i-001", "my-server", "CPU", 80)
        assert name == "[EC2] my-server CPUUtilization >80% (i-001)"

    def test_pretty_alarm_name_no_name_tag(self):
        name = _pretty_alarm_name("EC2", "i-001", "", "Memory", 90)
        assert name == "[EC2] i-001 mem_used_percent >90% (i-001)"

    def test_pretty_alarm_name_disk_root(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-root", 85)
        assert name == "[EC2] srv disk_used_percent(/) >85% (i-001)"

    def test_pretty_alarm_name_disk_data(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-data", 90)
        assert name == "[EC2] srv disk_used_percent(/data) >90% (i-001)"

    def test_pretty_alarm_name_rds_free_memory(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "FreeMemoryGB", 2)
        assert name == "[RDS] my-db FreeableMemory <2GB (db-001)"

    def test_pretty_alarm_name_rds_connections(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "Connections", 100)
        assert name == "[RDS] my-db DatabaseConnections >100 (db-001)"

    def test_pretty_alarm_name_float_threshold(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "CPU", 85.5)
        assert name == "[EC2] srv CPUUtilization >85.5% (i-001)"

    def test_extract_elb_dimension_from_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        assert _extract_elb_dimension(arn) == "app/my-alb/abc123"

    def test_extract_elb_dimension_fallback(self):
        assert _extract_elb_dimension("not-an-arn") == "not-an-arn"

    def test_get_alarm_defs_ec2(self):
        defs = _get_alarm_defs("EC2")
        assert len(defs) == 3
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "Memory", "Disk"}

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

    def _mock_cw_with_disk(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "xfs"},
                {"Name": "path", "Value": "/"},
            ]}
        ]}
        # _find_alarms_for_resource 용 paginator mock
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_ec2_creates_cpu_memory_disk_alarms(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert len(created) == 3
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        # 새 포맷 확인
        assert any("[EC2] my-server" in n for n in created)
        assert any("(i-001)" in n for n in created)
        assert mock_cw.put_metric_alarm.call_count == 3

    def test_ec2_custom_threshold_from_tag(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        cpu_call = [c for c in calls if c.kwargs["MetricName"] == "CPUUtilization"][0]
        assert cpu_call.kwargs["Threshold"] == 90.0
        # 알람 이름에 90% 포함
        assert ">90%" in cpu_call.kwargs["AlarmName"]

    def test_rds_creates_four_alarms(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Name": "my-db"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", tags)

        assert len(created) == 4
        assert mock_cw.put_metric_alarm.call_count == 4

    def test_rds_free_memory_threshold_converted_to_bytes(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Threshold_FreeMemoryGB": "4"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("db-001", "RDS", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        free_mem_call = [c for c in calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert free_mem_call.kwargs["Threshold"] == 4 * 1024 * 1024 * 1024

    def test_elb_extracts_dimension_from_arn(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(arn, "ELB", {"Monitoring": "on"})

        assert len(created) == 1
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        dims = kwargs["Dimensions"]
        assert dims[0]["Value"] == "app/my-alb/abc"

    def test_sns_arn_set_as_alarm_action(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args_list[0].kwargs
        assert kwargs["AlarmActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]
        assert kwargs["OKActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]

    def test_no_sns_arn_empty_actions(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "")
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args_list[0].kwargs
        assert kwargs["AlarmActions"] == []

    def test_client_error_logged_and_skipped(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "LimitExceeded", "Message": "too many"}}, "PutMetricAlarm"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        assert created == []

    def test_unknown_resource_type_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("x-001", "UNKNOWN", {})
        assert created == []

    def test_ec2_disk_alarm_has_extra_dimensions(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        calls = mock_cw.put_metric_alarm.call_args_list
        disk_call = [c for c in calls if c.kwargs["MetricName"] == "disk_used_percent"][0]
        dims = disk_call.kwargs["Dimensions"]
        dim_names = {d["Name"] for d in dims}
        assert "InstanceId" in dim_names
        assert "path" in dim_names
        assert "fstype" in dim_names
        assert "device" in dim_names

    def test_ec2_no_name_tag_uses_resource_id(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        # Name 태그 없으면 resource_id가 label로 사용됨
        assert any("[EC2] i-001" in n for n in created)


# ──────────────────────────────────────────────
# delete_alarms_for_resource
# ──────────────────────────────────────────────

class TestDeleteAlarms:

    def test_ec2_deletes_legacy_and_new_format(self):
        mock_cw = MagicMock()
        # paginator mock: 레거시 prefix 검색 + 새 포맷 전체 검색
        legacy_page = {"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
            {"AlarmName": "i-001-Memory-prod"},
        ]}
        new_page = {"MetricAlarms": [
            {"AlarmName": "[EC2] my-server CPUUtilization >80% (i-001)"},
            {"AlarmName": "[EC2] my-server mem_used_percent >80% (i-001)"},
        ]}
        mock_paginator = MagicMock()
        # 첫 번째 paginate: prefix 검색, 두 번째: 전체 검색
        mock_paginator.paginate.side_effect = [[legacy_page], [new_page]]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert len(deleted) == 4
        mock_cw.delete_alarms.assert_called_once()

    def test_no_alarms_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("x-001", "UNKNOWN")
        assert deleted == []

    def test_client_error_returns_empty(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator
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
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[]):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        # 알람이 없으면 전체 생성
        assert len(result["created"]) > 0

    def test_matching_threshold_is_ok(self):
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            if names:
                return {"MetricAlarms": [
                    {"AlarmName": n, "Threshold": 80.0} for n in names
                ]}
            return {"MetricAlarms": []}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["ok"]) == 3
        assert result["created"] == []
        assert result["updated"] == []

    def test_mismatched_threshold_gets_updated(self):
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >70% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            if names:
                for n in names:
                    thr = 70.0 if "CPUUtilization" in n else 80.0
                    return {"MetricAlarms": [{"AlarmName": n, "Threshold": thr}]}
            return {"MetricAlarms": []}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        # _find: 기존 알람 있음, _delete: 재생성 시 삭제
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert len(result["updated"]) > 0
