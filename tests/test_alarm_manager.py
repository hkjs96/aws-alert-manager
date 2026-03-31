"""
alarm_manager 핵심 로직 단위 테스트

Helper 함수, 디멘션 빌드, 알람 생성, 메타데이터, 태그 파싱,
동적 알람, 퍼센트 임계치, DocDB/AuroraRDS 통합 테스트.
"""

from unittest.mock import MagicMock, patch

import pytest

from common import HARDCODED_DEFAULTS
from common.alarm_manager import (
    _alarm_name,
    _build_alarm_description,
    _build_dimensions,
    _create_dynamic_alarm,
    _extract_elb_dimension,
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
    _HARDCODED_METRIC_KEYS,
    _METRIC_DISPLAY,
    _metric_name_to_key,
    _parse_alarm_metadata,
    _parse_threshold_tags,
    _pretty_alarm_name,
    _resolve_free_memory_threshold,
    _resolve_metric_dimensions,
    _resolve_tg_namespace,
    _select_best_dimensions,
    _shorten_elb_resource_id,
    _find_alarms_for_resource,
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    from common._clients import _get_cw_client
    _get_cw_client.cache_clear()
    yield
    _get_cw_client.cache_clear()


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
        assert name == "[EC2] my-server CPUUtilization > 80% (TagName: i-001)"

    def test_pretty_alarm_name_no_name_tag(self):
        name = _pretty_alarm_name("EC2", "i-001", "", "Memory", 90)
        assert name == "[EC2] i-001 mem_used_percent > 90% (TagName: i-001)"

    def test_pretty_alarm_name_disk_root(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-root", 85)
        assert name == "[EC2] srv disk_used_percent(/) > 85% (TagName: i-001)"

    def test_pretty_alarm_name_disk_data(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-data", 90)
        assert name == "[EC2] srv disk_used_percent(/data) > 90% (TagName: i-001)"

    def test_pretty_alarm_name_rds_free_memory(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "FreeMemoryGB", 2)
        assert name == "[RDS] my-db FreeableMemory < 2GB (TagName: db-001)"

    def test_pretty_alarm_name_rds_connections(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "Connections", 100)
        assert name == "[RDS] my-db DatabaseConnections > 100 (TagName: db-001)"

    def test_pretty_alarm_name_float_threshold(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "CPU", 85.5)
        assert name == "[EC2] srv CPUUtilization > 85.5% (TagName: i-001)"

    def test_pretty_alarm_name_always_within_255_chars(self):
        long_name = "a" * 256
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith("(TagName: i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_label_first(self):
        long_name = "my-very-long-server-name-" * 10
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert "CPUUtilization" in name
        assert name.endswith("(TagName: i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_display_metric_when_label_insufficient(self):
        long_id = "i-" + "a" * 200
        name = _pretty_alarm_name("EC2", long_id, "srv", "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"(TagName: {long_id})")

    def test_pretty_alarm_name_preserves_resource_id_always(self):
        long_id = "i-" + "x" * 150
        long_name = "n" * 200
        name = _pretty_alarm_name("EC2", long_id, long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"(TagName: {long_id})")

    def test_pretty_alarm_name_short_inputs_unchanged(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "CPU", 80)
        assert name == "[RDS] my-db CPUUtilization > 80% (TagName: db-001)"
        assert len(name) <= 255

    def test_pretty_alarm_name_alb_suffix_short_id(self):
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        name = _pretty_alarm_name("ALB", alb_arn, "my-alb", "CPU", 80.0)
        assert name.endswith("(TagName: my-alb/1234567890abcdef)")

    def test_pretty_alarm_name_nlb_suffix_short_id(self):
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/1234567890abcdef"
        name = _pretty_alarm_name("NLB", nlb_arn, "my-nlb", "CPU", 80.0)
        assert name.endswith("(TagName: my-nlb/1234567890abcdef)")

    def test_pretty_alarm_name_tg_suffix_short_id(self):
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/1234567890abcdef"
        name = _pretty_alarm_name("TG", tg_arn, "my-tg", "CPU", 80.0)
        assert name.endswith("(TagName: my-tg/1234567890abcdef)")

    def test_pretty_alarm_name_ec2_suffix_unchanged(self):
        name = _pretty_alarm_name("EC2", "i-xxx", "my-ec2", "CPU", 80.0)
        assert name.endswith("(TagName: i-xxx)")

    def test_pretty_alarm_name_rds_suffix_unchanged(self):
        name = _pretty_alarm_name("RDS", "db-test", "my-rds", "CPU", 80.0)
        assert name.endswith("(TagName: db-test)")

    def test_extract_elb_dimension_from_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        assert _extract_elb_dimension(arn) == "app/my-alb/abc123"

    def test_extract_elb_dimension_tg_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        assert _extract_elb_dimension(arn) == "targetgroup/my-tg/abc123"

    def test_extract_elb_dimension_fallback(self):
        assert _extract_elb_dimension("not-an-arn") == "not-an-arn"

    def test_get_alarm_defs_ec2(self):
        defs = _get_alarm_defs("EC2")
        assert len(defs) == 4
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "Memory", "Disk", "StatusCheckFailed"}

    def test_get_alarm_defs_rds(self):
        defs = _get_alarm_defs("RDS")
        assert len(defs) == 7
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency", "ConnectionAttempts"}

    def test_get_alarm_defs_elb(self):
        defs = _get_alarm_defs("ELB")
        assert defs == []

    def test_get_alarm_defs_unknown(self):
        assert _get_alarm_defs("UNKNOWN") == []

    def test_get_alarm_defs_alb(self):
        defs = _get_alarm_defs("ALB")
        assert len(defs) == 5
        metrics = {d["metric"] for d in defs}
        assert metrics == {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}
        for d in defs:
            assert d["namespace"] == "AWS/ApplicationELB"
            assert d["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_nlb(self):
        defs = _get_alarm_defs("NLB")
        assert len(defs) == 5
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}
        for d in defs:
            assert d["namespace"] == "AWS/NetworkELB"
            assert d["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_tg(self):
        defs = _get_alarm_defs("TG")
        assert len(defs) == 4
        metrics = {d["metric"] for d in defs}
        assert metrics == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}
        for d in defs:
            assert d["dimension_key"] == "TargetGroup"

    def test_get_alarm_defs_elb_removed(self):
        defs = _get_alarm_defs("ELB")
        assert defs == []

    def test_hardcoded_metric_keys_alb_nlb_tg(self):
        from common.alarm_manager import _HARDCODED_METRIC_KEYS
        assert "ALB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["ALB"] == {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}
        assert "NLB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["NLB"] == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}
        assert "TG" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["TG"] == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}
        assert "ELB" not in _HARDCODED_METRIC_KEYS

    def test_namespace_map_alb_nlb_tg(self):
        from common.alarm_manager import _NAMESPACE_MAP
        assert _NAMESPACE_MAP["ALB"] == ["AWS/ApplicationELB"]
        assert _NAMESPACE_MAP["NLB"] == ["AWS/NetworkELB"]
        assert _NAMESPACE_MAP["TG"] == ["AWS/ApplicationELB", "AWS/NetworkELB"]
        assert "ELB" not in _NAMESPACE_MAP

    def test_dimension_key_map_alb_nlb_tg(self):
        from common.alarm_manager import _DIMENSION_KEY_MAP
        assert _DIMENSION_KEY_MAP["ALB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["NLB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["TG"] == "TargetGroup"
        assert "ELB" not in _DIMENSION_KEY_MAP


# ──────────────────────────────────────────────
# _build_dimensions / _resolve_tg_namespace 테스트
# ──────────────────────────────────────────────

class TestBuildDimensions:

    def test_tg_returns_compound_dimensions(self):
        alarm_def = _get_alarm_defs("TG")[0]
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def456"
        tags = {"_lb_arn": lb_arn}
        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)
        assert len(dims) == 2
        assert dims[0] == {"Name": "TargetGroup", "Value": "targetgroup/my-tg/abc123"}
        assert dims[1] == {"Name": "LoadBalancer", "Value": "app/my-alb/def456"}

    def test_tg_nlb_compound_dimensions(self):
        alarm_def = _get_alarm_defs("TG")[0]
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        tags = {"_lb_arn": lb_arn, "_lb_type": "network"}
        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)
        assert len(dims) == 2
        assert dims[0]["Name"] == "TargetGroup"
        assert dims[1] == {"Name": "LoadBalancer", "Value": "net/my-nlb/def456"}

    def test_alb_returns_single_loadbalancer_dimension(self):
        alarm_def = _get_alarm_defs("ALB")[0]
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        dims = _build_dimensions(alarm_def, alb_arn, "ALB", {})
        assert len(dims) == 1
        assert dims[0] == {"Name": "LoadBalancer", "Value": "app/my-alb/abc"}

    def test_nlb_returns_single_loadbalancer_dimension(self):
        alarm_def = _get_alarm_defs("NLB")[0]
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/abc"
        dims = _build_dimensions(alarm_def, nlb_arn, "NLB", {})
        assert len(dims) == 1
        assert dims[0] == {"Name": "LoadBalancer", "Value": "net/my-nlb/abc"}

    def test_ec2_returns_instance_id_dimension(self):
        alarm_def = _get_alarm_defs("EC2")[0]
        dims = _build_dimensions(alarm_def, "i-001", "EC2", {})
        assert len(dims) == 1
        assert dims[0] == {"Name": "InstanceId", "Value": "i-001"}

    def test_rds_returns_db_instance_dimension(self):
        alarm_def = _get_alarm_defs("RDS")[0]
        dims = _build_dimensions(alarm_def, "db-001", "RDS", {})
        assert len(dims) == 1
        assert dims[0] == {"Name": "DBInstanceIdentifier", "Value": "db-001"}

    def test_extra_dimensions_appended(self):
        alarm_def = {
            "dimension_key": "InstanceId",
            "extra_dimensions": [{"Name": "path", "Value": "/"}],
        }
        dims = _build_dimensions(alarm_def, "i-001", "EC2", {})
        assert len(dims) == 2
        assert dims[1] == {"Name": "path", "Value": "/"}

    def test_tg_with_extra_dimensions(self):
        alarm_def = {
            "dimension_key": "TargetGroup",
            "extra_dimensions": [{"Name": "AvailabilityZone", "Value": "us-east-1a"}],
        }
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def"
        tags = {"_lb_arn": lb_arn}
        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)
        assert len(dims) == 3
        assert dims[0]["Name"] == "TargetGroup"
        assert dims[1]["Name"] == "LoadBalancer"
        assert dims[2] == {"Name": "AvailabilityZone", "Value": "us-east-1a"}

    def test_tg_new_alarms_have_compound_dimensions(self):
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def456"
        tags = {"_lb_arn": lb_arn}
        for alarm_def in _get_alarm_defs("TG"):
            if alarm_def["metric"] in ("RequestCountPerTarget", "TGResponseTime"):
                dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)
                assert len(dims) == 2, f"{alarm_def['metric']} should have 2 dimensions"
                assert dims[0] == {"Name": "TargetGroup", "Value": "targetgroup/my-tg/abc123"}
                assert dims[1] == {"Name": "LoadBalancer", "Value": "app/my-alb/def456"}


class TestResolveTgNamespace:

    def test_network_lb_type_returns_network_elb(self):
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": "network"}
        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/NetworkELB"

    def test_application_lb_type_returns_alarm_def_namespace(self):
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": "application"}
        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_missing_lb_type_returns_alarm_def_namespace(self):
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {}
        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_empty_lb_type_returns_alarm_def_namespace(self):
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": ""}
        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_tg_new_alarms_network_lb_type_returns_network_elb(self):
        tags = {"_lb_type": "network"}
        for alarm_def in _get_alarm_defs("TG"):
            if alarm_def["metric"] in ("RequestCountPerTarget", "TGResponseTime"):
                ns = _resolve_tg_namespace(alarm_def, tags)
                assert ns == "AWS/NetworkELB", (
                    f"{alarm_def['metric']} with network LB should use AWS/NetworkELB"
                )


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
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_ec2_creates_cpu_memory_disk_alarms(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert len(created) == 4
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        assert any("[EC2] my-server" in n for n in created)
        assert any("(TagName: i-001)" in n for n in created)
        assert mock_cw.put_metric_alarm.call_count == 4

    def test_ec2_custom_threshold_from_tag(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "90"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        cpu_call = [c for c in calls if c.kwargs["MetricName"] == "CPUUtilization"][0]
        assert cpu_call.kwargs["Threshold"] == 90.0
        assert "> 90%" in cpu_call.kwargs["AlarmName"]

    def test_rds_creates_seven_alarms(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Name": "my-db"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", tags)

        assert len(created) == 7
        assert mock_cw.put_metric_alarm.call_count == 7

    def test_rds_free_memory_threshold_converted_to_bytes(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Threshold_FreeMemoryGB": "4"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("db-001", "RDS", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        free_mem_call = [c for c in calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert free_mem_call.kwargs["Threshold"] == 4 * 1024 * 1024 * 1024

    def test_alb_extracts_dimension_from_arn(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(arn, "ALB", {"Monitoring": "on"})

        assert len(created) == 5
        for call in mock_cw.put_metric_alarm.call_args_list:
            dims = call.kwargs["Dimensions"]
            assert len(dims) == 1
            assert dims[0]["Name"] == "LoadBalancer"
            assert dims[0]["Value"] == "app/my-alb/abc"

    def test_sns_arn_set_as_alarm_action(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args_list[0].kwargs
        assert kwargs["AlarmActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]
        assert kwargs["OKActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]

    def test_no_sns_arn_empty_actions(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "")
        mock_cw = self._mock_cw_with_disk()
        with patch("common._clients._get_cw_client", return_value=mock_cw):
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
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        assert created == []

    def test_unknown_resource_type_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("x-001", "UNKNOWN", {})
        assert created == []

    def test_ec2_disk_alarm_has_extra_dimensions(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common._clients._get_cw_client", return_value=mock_cw):
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
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        assert any("[EC2] i-001" in n for n in created)


# ──────────────────────────────────────────────
# AlarmDescription 메타데이터 테스트
# ──────────────────────────────────────────────

class TestAlarmMetadata:

    def test_build_alarm_description_includes_json(self):
        desc = _build_alarm_description("EC2", "i-001", "CPU", "Auto-created")
        assert "Auto-created" in desc
        assert '{"metric_key":"CPU"' in desc
        assert '"resource_id":"i-001"' in desc
        assert '"resource_type":"EC2"' in desc
        assert " | " in desc

    def test_build_alarm_description_max_1024_chars(self):
        long_prefix = "x" * 2000
        desc = _build_alarm_description("EC2", "i-001", "CPU", long_prefix)
        assert len(desc) <= 1024

    def test_parse_alarm_metadata_valid(self):
        desc = 'Auto-created | {"metric_key":"CPU","resource_id":"i-001","resource_type":"EC2"}'
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["metric_key"] == "CPU"
        assert meta["resource_id"] == "i-001"
        assert meta["resource_type"] == "EC2"

    def test_parse_alarm_metadata_legacy_no_json(self):
        desc = "Auto-created by AWS Monitoring Engine for EC2 i-001"
        meta = _parse_alarm_metadata(desc)
        assert meta is None

    def test_parse_alarm_metadata_empty(self):
        assert _parse_alarm_metadata("") is None
        assert _parse_alarm_metadata(None) is None

    def test_create_alarms_includes_json_in_description(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "xfs"},
                {"Name": "path", "Value": "/"},
            ]}
        ]}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {"Name": "srv"})

        for call in mock_cw.put_metric_alarm.call_args_list:
            desc = call.kwargs["AlarmDescription"]
            meta = _parse_alarm_metadata(desc)
            assert meta is not None, f"Missing JSON metadata in: {desc}"
            assert meta["resource_id"] == "i-001"
            assert meta["resource_type"] == "EC2"
            assert "metric_key" in meta

    def test_roundtrip_build_and_parse(self):
        desc = _build_alarm_description("RDS", "db-001", "FreeMemoryGB", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["metric_key"] == "FreeMemoryGB"
        assert meta["resource_id"] == "db-001"
        assert meta["resource_type"] == "RDS"

    def test_alarm_description_preserves_full_arn_alb(self):
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        desc = _build_alarm_description("ALB", alb_arn, "RequestCount", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == alb_arn

    def test_alarm_description_preserves_full_arn_nlb(self):
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/abcdef1234567890"
        desc = _build_alarm_description("NLB", nlb_arn, "ProcessedBytes", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == nlb_arn

    def test_alarm_description_preserves_full_arn_tg(self):
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/fedcba0987654321"
        desc = _build_alarm_description("TG", tg_arn, "HealthyHostCount", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == tg_arn


# ──────────────────────────────────────────────
# _parse_threshold_tags 테스트
# ──────────────────────────────────────────────

class TestParseThresholdTags:

    def test_extracts_dynamic_metric_for_ec2(self):
        tags = {"Threshold_NetworkIn": "1000000", "Threshold_CPU": "90"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "NetworkIn" in result
        assert result["NetworkIn"] == (1000000.0, "GreaterThanThreshold")
        assert "CPU" not in result

    def test_extracts_dynamic_metric_for_rds(self):
        tags = {"Threshold_ReadLatency": "0.01", "Threshold_FreeMemoryGB": "4", "Threshold_CustomRDS": "50"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "ReadLatency" not in result
        assert "FreeMemoryGB" not in result
        assert "CustomRDS" in result
        assert result["CustomRDS"] == (50.0, "GreaterThanThreshold")

    def test_skips_disk_prefix_tags(self):
        tags = {"Threshold_Disk_root": "85", "Threshold_Disk_data": "90"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_non_numeric_value(self):
        tags = {"Threshold_CustomMetric": "not-a-number"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_zero_or_negative_value(self):
        tags = {"Threshold_CustomMetric": "0", "Threshold_Another": "-5"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_empty_metric_name(self):
        tags = {"Threshold_": "100"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_tag_key_over_128_chars(self):
        long_key = "Threshold_" + "A" * 119
        tags = {long_key: "100"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_accepts_tag_key_at_128_chars(self):
        metric = "A" * 118
        tags = {f"Threshold_{metric}": "50"}
        result = _parse_threshold_tags(tags, "EC2")
        assert metric in result

    def test_no_threshold_tags_returns_empty(self):
        tags = {"Monitoring": "on", "Name": "my-server"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_multiple_dynamic_metrics(self):
        tags = {
            "Threshold_NetworkIn": "1000",
            "Threshold_NetworkOut": "2000",
            "Threshold_DiskReadOps": "500",
        }
        result = _parse_threshold_tags(tags, "EC2")
        assert len(result) == 3

    def test_off_value_excluded_from_result(self):
        tags = {"Threshold_CustomMetric": "off"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert result == {}

    def test_off_value_case_insensitive(self):
        tags = {"Threshold_CustomMetric": "OFF"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert result == {}

    def test_positive_number_included_alongside_off(self):
        tags = {
            "Threshold_CustomMetric": "off",
            "Threshold_NetworkIn": "1000",
        }
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert "NetworkIn" in result
        assert result["NetworkIn"] == (1000.0, "GreaterThanThreshold")

    def test_parse_threshold_tags_excludes_new_hardcoded_keys(self):
        tags = {"Threshold_ELB5XX": "100", "Threshold_TargetResponseTime": "10", "Threshold_CustomALB": "42"}
        result = _parse_threshold_tags(tags, "ALB")
        assert "ELB5XX" not in result
        assert "TargetResponseTime" not in result
        assert "CustomALB" in result
        assert result["CustomALB"] == (42.0, "GreaterThanThreshold")

        tags = {"Threshold_TCPClientReset": "200", "Threshold_TCPTargetReset": "300", "Threshold_CustomNLB": "55"}
        result = _parse_threshold_tags(tags, "NLB")
        assert "TCPClientReset" not in result
        assert "TCPTargetReset" not in result
        assert "CustomNLB" in result
        assert result["CustomNLB"] == (55.0, "GreaterThanThreshold")

        tags = {"Threshold_StatusCheckFailed": "1", "Threshold_CustomEC2": "77"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "StatusCheckFailed" not in result
        assert "CustomEC2" in result
        assert result["CustomEC2"] == (77.0, "GreaterThanThreshold")

        tags = {"Threshold_ReadLatency": "0.05", "Threshold_WriteLatency": "0.05", "Threshold_CustomRDS": "33"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "ReadLatency" not in result
        assert "WriteLatency" not in result
        assert "CustomRDS" in result
        assert result["CustomRDS"] == (33.0, "GreaterThanThreshold")

        tags = {"Threshold_RequestCountPerTarget": "500", "Threshold_TGResponseTime": "3", "Threshold_CustomTG": "99"}
        result = _parse_threshold_tags(tags, "TG")
        assert "RequestCountPerTarget" not in result
        assert "TGResponseTime" not in result
        assert "CustomTG" in result
        assert result["CustomTG"] == (99.0, "GreaterThanThreshold")

    def test_excludes_new_alb_rds_hardcoded_keys(self):
        alb_tags = {
            "Threshold_ELB4XX": "200",
            "Threshold_TargetConnectionError": "100",
            "Threshold_CustomALBMetric": "42",
        }
        result = _parse_threshold_tags(alb_tags, "ALB")
        assert "ELB4XX" not in result
        assert "TargetConnectionError" not in result
        assert "CustomALBMetric" in result
        assert result["CustomALBMetric"] == (42.0, "GreaterThanThreshold")

        rds_tags = {
            "Threshold_ConnectionAttempts": "1000",
            "Threshold_CustomRDSMetric": "55",
        }
        result = _parse_threshold_tags(rds_tags, "RDS")
        assert "ConnectionAttempts" not in result
        assert "CustomRDSMetric" in result
        assert result["CustomRDSMetric"] == (55.0, "GreaterThanThreshold")

    def test_lt_prefix_returns_less_than_threshold(self):
        tags = {"Threshold_LT_BufferCacheHitRatio": "95"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "BufferCacheHitRatio" in result
        assert result["BufferCacheHitRatio"] == (95.0, "LessThanThreshold")


# ──────────────────────────────────────────────
# _resolve_metric_dimensions 테스트
# ──────────────────────────────────────────────

class TestResolveMetricDimensions:

    def test_resolves_ec2_metric(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is not None
        namespace, dims = result
        assert namespace in ("AWS/EC2", "CWAgent")
        assert any(d["Name"] == "InstanceId" for d in dims)

    def test_returns_none_when_metric_not_found(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NonExistent", "EC2")

        assert result is None

    def test_resolves_rds_metric(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "db-001"}]}
        ]}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("db-001", "ReadLatency", "RDS")

        assert result is not None
        namespace, dims = result
        assert namespace == "AWS/RDS"

    def test_elb_uses_arn_suffix_as_dimension(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "LoadBalancer", "Value": "app/my-alb/abc"}]}
        ]}
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions(arn, "ProcessedBytes", "ALB")

        assert result is not None

    def test_client_error_returns_none(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "fail"}}, "ListMetrics"
        )
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is None


# ──────────────────────────────────────────────
# _create_dynamic_alarm 테스트
# ──────────────────────────────────────────────

class TestCreateDynamicAlarm:

    def test_creates_alarm_when_metric_resolved(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NetworkIn", 1000000.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert "NetworkIn" in created[0]
        mock_cw.put_metric_alarm.assert_called_once()
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["Threshold"] == 1000000.0
        assert kwargs["MetricName"] == "NetworkIn"

    def test_skips_when_metric_not_resolved(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NonExistent", 100.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert created == []
        mock_cw.put_metric_alarm.assert_not_called()

    def test_alarm_name_within_255_chars(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        long_name = "x" * 200
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", long_name,
                "NetworkIn", 100.0, mock_cw, "", created,
            )

        assert len(created) == 1
        assert len(created[0]) <= 255

    def test_client_error_does_not_add_to_created(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        mock_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "LimitExceeded", "Message": "too many"}},
            "PutMetricAlarm",
        )
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "srv",
                "NetworkIn", 100.0, mock_cw, "", created,
            )

        assert created == []

    def test_dynamic_alarm_alb_suffix_short_id(self):
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "LoadBalancer", "Value": "app/my-alb/1234567890abcdef"}]}
        ]}
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                alb_arn, "ALB", "my-alb",
                "CustomMetric", 100.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(TagName: my-alb/1234567890abcdef)")

    def test_dynamic_alarm_tg_suffix_short_id(self):
        mock_cw = MagicMock()
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abcdef1234567890"
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "TargetGroup", "Value": "targetgroup/my-tg/abcdef1234567890"}]}
        ]}
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                tg_arn, "TG", "my-tg",
                "CustomMetric", 50.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(TagName: my-tg/abcdef1234567890)")

    def test_dynamic_alarm_ec2_suffix_unchanged(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NetworkIn", 1000.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(TagName: i-001)")


# ──────────────────────────────────────────────
# _shorten_elb_resource_id() 단위 테스트
# ──────────────────────────────────────────────

class TestShortenElbResourceId:

    def test_alb_arn_returns_name_hash(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "ALB") == "my-alb/1234567890abcdef"

    def test_nlb_arn_returns_name_hash(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "NLB") == "my-nlb/1234567890abcdef"

    def test_tg_arn_returns_name_hash(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "TG") == "my-tg/1234567890abcdef"

    def test_ec2_instance_id_unchanged(self):
        assert _shorten_elb_resource_id("i-0abc123def456789a", "EC2") == "i-0abc123def456789a"

    def test_rds_identifier_unchanged(self):
        assert _shorten_elb_resource_id("db-test", "RDS") == "db-test"

    def test_non_arn_string_with_alb_type_unchanged(self):
        assert _shorten_elb_resource_id("some-random-string", "ALB") == "some-random-string"

    def test_empty_string_returns_empty(self):
        assert _shorten_elb_resource_id("", "ALB") == ""

    def test_idempotent_alb_short_id(self):
        short_id = "my-alb/1234567890abcdef"
        assert _shorten_elb_resource_id(short_id, "ALB") == short_id


# ──────────────────────────────────────────────
# _select_best_dimensions 테스트
# ──────────────────────────────────────────────

class TestSelectBestDimensions:

    def test_primary_only_preferred(self):
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        assert result == [{"Name": "InstanceId", "Value": "i-001"}]

    def test_no_primary_only_prefers_no_az_min_dims(self):
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
                {"Name": "fstype", "Value": "xfs"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        assert result == [
            {"Name": "InstanceId", "Value": "i-001"},
            {"Name": "device", "Value": "xvda"},
        ]

    def test_all_have_az_selects_min_dims(self):
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
                {"Name": "device", "Value": "xvda"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        assert result == [
            {"Name": "InstanceId", "Value": "i-001"},
            {"Name": "AvailabilityZone", "Value": "us-east-1a"},
        ]

    def test_empty_list_returns_empty(self):
        result = _select_best_dimensions([], "InstanceId")
        assert result == []


# ──────────────────────────────────────────────
# _resolve_free_memory_threshold() 검증
# ──────────────────────────────────────────────

class TestResolveFreeMemoryThreshold:
    """퍼센트 기반 FreeableMemory 임계치 해석 검증.
    Validates: Requirements 5.1, 5.2, 5.3, 5.5, 6.5
    """

    def test_pct_with_total_memory(self):
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "_total_memory_bytes": "17179869184",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(3435973836.8)

    def test_pct_takes_precedence_over_gb(self):
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "Threshold_FreeMemoryGB": "4",
            "_total_memory_bytes": "17179869184",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(3435973836.8)

    def test_invalid_pct_falls_back_to_default_pct(self, caplog):
        tags = {
            "Threshold_FreeMemoryPct": "150",
            "Threshold_FreeMemoryGB": "4",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)
        assert any("FreeMemoryPct" in msg for msg in caplog.messages)

    def test_missing_total_memory_falls_back_to_gb(self, caplog):
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "Threshold_FreeMemoryGB": "4",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == 4
        assert cw_bytes == pytest.approx(4 * 1024 * 1024 * 1024)
        assert any("total_memory" in msg.lower() or "_total_memory_bytes" in msg for msg in caplog.messages)

    def test_no_pct_tag_uses_gb_logic(self):
        tags = {
            "Threshold_FreeMemoryGB": "3",
            "_total_memory_bytes": "17179869184",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_no_pct_no_gb_uses_hardcoded_default(self):
        tags = {"_total_memory_bytes": "17179869184"}
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_zero_invalid(self, caplog):
        tags = {
            "Threshold_FreeMemoryPct": "0",
            "Threshold_FreeMemoryGB": "2",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_100_invalid(self, caplog):
        tags = {
            "Threshold_FreeMemoryPct": "100",
            "Threshold_FreeMemoryGB": "2",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_non_numeric_falls_back(self, caplog):
        tags = {
            "Threshold_FreeMemoryPct": "abc",
            "Threshold_FreeMemoryGB": "3",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)


# ──────────────────────────────────────────────
# DocDB 알람 생성 통합 테스트
# ──────────────────────────────────────────────

class TestDocDBAlarmCreation:
    """DocDB 알람 생성 통합 테스트.
    Validates: Requirements 5.1, 5.2, 5.3, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
    """

    def _mock_cw(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_docdb_creates_three_alarms(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Name": "my-docdb"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        assert len(created) == 3
        assert mock_cw.put_metric_alarm.call_count == 3

    def test_docdb_alarm_name_prefix(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Name": "my-docdb"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        for name in created:
            assert name.startswith("[DocDB] "), f"Alarm name missing [DocDB] prefix: {name}"

    def test_docdb_alarm_description_metadata(self):
        import json
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Name": "my-docdb"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        for call in mock_cw.put_metric_alarm.call_args_list:
            desc = call.kwargs["AlarmDescription"]
            idx = desc.rfind(" | {")
            json_str = desc[idx + 3:] if idx >= 0 else desc
            metadata = json.loads(json_str)
            assert metadata["resource_type"] == "DocDB", f"Missing resource_type in: {desc}"

    def test_docdb_alarm_dimensions(self):
        mock_cw = self._mock_cw()
        db_id = "docdb-inst-1"
        tags = {"Monitoring": "on"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource(db_id, "DocDB", tags)
        for call in mock_cw.put_metric_alarm.call_args_list:
            dims = call.kwargs["Dimensions"]
            assert dims == [{"Name": "DBInstanceIdentifier", "Value": db_id}]

    def test_docdb_threshold_cpu_tag_override(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Threshold_CPU": "90"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        calls = mock_cw.put_metric_alarm.call_args_list
        cpu_call = [c for c in calls if c.kwargs["MetricName"] == "CPUUtilization"][0]
        assert cpu_call.kwargs["Threshold"] == 90.0

    def test_docdb_threshold_free_memory_gb_tag_override(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Threshold_FreeMemoryGB": "4"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        calls = mock_cw.put_metric_alarm.call_args_list
        mem_call = [c for c in calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert mem_call.kwargs["Threshold"] == 4 * 1073741824

    def test_docdb_alarm_name_contains_resource_id_suffix(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        for name in created:
            assert name.endswith("(TagName: docdb-inst-1)"), f"Alarm name missing suffix: {name}"


# ──────────────────────────────────────────────
# DocDB E2E 통합 테스트
# ──────────────────────────────────────────────

class TestDocDBEndToEnd:
    """DocDB 전체 통합 와이어링 검증.
    Validates: Requirements 7.1, 7.2, 7.3, 8.1, 8.3, 10.1, 10.2, 12.1, 12.2
    """

    def _mock_cw(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_docdb_create_alarms_three_with_prefix(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        assert len(created) == 3
        for name in created:
            assert name.startswith("[DocDB] "), f"Missing [DocDB] prefix: {name}"

    def test_docdb_sync_alarms_creates_when_none_exist(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource("docdb-inst-1", "DocDB", tags)
        assert len(result["created"]) == 3
        for name in result["created"]:
            assert name.startswith("[DocDB] "), f"Missing [DocDB] prefix: {name}"

    def test_docdb_sync_alarms_all_ok_when_matching(self):
        import json
        mock_cw = self._mock_cw()
        db_id = "docdb-inst-1"
        tags = {"Monitoring": "on", "Name": "my-docdb"}

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(db_id, "DocDB", tags)

        existing_alarms = []
        for call in mock_cw.put_metric_alarm.call_args_list:
            kw = call.kwargs
            existing_alarms.append({
                "AlarmName": kw["AlarmName"],
                "Namespace": kw["Namespace"],
                "MetricName": kw["MetricName"],
                "Dimensions": kw["Dimensions"],
                "Threshold": kw["Threshold"],
                "ComparisonOperator": kw["ComparisonOperator"],
                "Statistic": kw["Statistic"],
                "Period": kw["Period"],
                "EvaluationPeriods": kw["EvaluationPeriods"],
                "AlarmDescription": kw.get("AlarmDescription", ""),
                "AlarmActions": kw.get("AlarmActions", []),
                "OKActions": kw.get("OKActions", []),
            })

        mock_cw2 = MagicMock()
        mock_cw2.describe_alarms.return_value = {"MetricAlarms": existing_alarms}

        with patch("common._clients._get_cw_client", return_value=mock_cw2), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=created):
            result = sync_alarms_for_resource(db_id, "DocDB", tags)

        assert len(result["ok"]) == 3
        assert result["created"] == []
        assert result["updated"] == []


# ──────────────────────────────────────────────
# AuroraRDS 통합 시나리오 테스트
# ──────────────────────────────────────────────

class TestAuroraRDSIntegration:
    """AuroraRDS 알람 생성 → sync → 삭제 end-to-end 통합 테스트.
    Validates: Requirements 6.2, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
    """

    @staticmethod
    def _make_mock_cw():
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.delete_alarms.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        return mock_cw

    def test_create_aurora_rds_creates_five_alarms(self):
        mock_cw = self._make_mock_cw()
        tags = {
            "Monitoring": "on", "Name": "my-aurora",
            "_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "true",
        }
        db_id = "aurora-db-001"
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", tags)

        assert len(result["created"]) == 5
        created_names = result["created"]
        assert all(n.startswith("[AuroraRDS] ") for n in created_names)
        assert all(n.endswith(f"(TagName: {db_id})") for n in created_names)
        assert any("CPUUtilization" in n for n in created_names)
        assert any("FreeableMemory" in n for n in created_names)
        assert any("DatabaseConnections" in n for n in created_names)
        assert any("FreeLocalStorage" in n for n in created_names)
        assert any("AuroraReplicaLagMaximum" in n for n in created_names)

    def test_sync_aurora_rds_matching_thresholds_ok(self):
        import json
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-002"
        existing = [
            f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory < 2GB (TagName: {db_id})",
            f"[AuroraRDS] my-aurora DatabaseConnections > 100 (TagName: {db_id})",
            f"[AuroraRDS] my-aurora FreeLocalStorage < 10GB (TagName: {db_id})",
            f"[AuroraRDS] my-aurora AuroraReplicaLagMaximum > 2000000μs (TagName: {db_id})",
        ]

        def _make_desc(metric_key):
            meta = json.dumps(
                {"metric_key": metric_key, "resource_id": db_id, "resource_type": "AuroraRDS"},
                separators=(",", ":"),
            )
            return f"Auto-created | {meta}"

        alarm_data = {
            "CPUUtilization": ("CPU", 80.0),
            "FreeableMemory": ("FreeMemoryGB", 2.0 * 1073741824),
            "DatabaseConnections": ("Connections", 100.0),
            "FreeLocalStorage": ("FreeLocalStorageGB", 10.0 * 1073741824),
            "AuroraReplicaLagMaximum": ("ReplicaLag", 2000000.0),
        }

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                for cw_metric, (mk, thr) in alarm_data.items():
                    if cw_metric in n:
                        alarms.append({
                            "AlarmName": n, "Threshold": thr, "MetricName": cw_metric,
                            "AlarmDescription": _make_desc(mk),
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        })
                        break
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", {
                "Name": "my-aurora",
                "_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "true",
            })

        assert len(result["ok"]) == 5
        assert result["created"] == []
        assert result["updated"] == []

    def test_resync_after_tag_change_updates_threshold(self):
        import json
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-003"
        existing = [
            f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory < 2GB (TagName: {db_id})",
            f"[AuroraRDS] my-aurora DatabaseConnections > 100 (TagName: {db_id})",
            f"[AuroraRDS] my-aurora FreeLocalStorage < 10GB (TagName: {db_id})",
            f"[AuroraRDS] my-aurora AuroraReplicaLagMaximum > 2000000μs (TagName: {db_id})",
        ]

        def _make_desc(metric_key):
            meta = json.dumps(
                {"metric_key": metric_key, "resource_id": db_id, "resource_type": "AuroraRDS"},
                separators=(",", ":"),
            )
            return f"Auto-created | {meta}"

        alarm_data = {
            "CPUUtilization": ("CPU", 80.0),
            "FreeableMemory": ("FreeMemoryGB", 2.0 * 1073741824),
            "DatabaseConnections": ("Connections", 100.0),
            "FreeLocalStorage": ("FreeLocalStorageGB", 10.0 * 1073741824),
            "AuroraReplicaLagMaximum": ("ReplicaLag", 2000000.0),
        }

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                for cw_metric, (mk, thr) in alarm_data.items():
                    if cw_metric in n:
                        alarms.append({
                            "AlarmName": n, "Threshold": thr, "MetricName": cw_metric,
                            "AlarmDescription": _make_desc(mk),
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        })
                        break
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        tags = {
            "Name": "my-aurora",
            "Threshold_CPU": "90", "Threshold_FreeMemoryGB": "4",
            "Threshold_Connections": "200", "Threshold_FreeLocalStorageGB": "20",
            "Threshold_ReplicaLag": "3000000",
            "_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "true",
        }

        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", tags)

        assert len(result["updated"]) == 5

    def test_delete_aurora_rds_alarms(self):
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-004"
        alarm_names = [
            f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory < 2GB (TagName: {db_id})",
        ]
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"MetricAlarms": [{"AlarmName": n} for n in alarm_names]}
        ]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource(db_id, "AuroraRDS")

        assert len(deleted) == 2
        mock_cw.delete_alarms.assert_called_once()

    def test_create_aurora_rds_transform_threshold_applied(self):
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-005"
        tags = {
            "Monitoring": "on", "Name": "my-aurora",
            "Threshold_FreeMemoryGB": "4", "Threshold_FreeLocalStorageGB": "20",
        }
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource(db_id, "AuroraRDS", tags)

        put_calls = mock_cw.put_metric_alarm.call_args_list
        mem_call = [c for c in put_calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert mem_call.kwargs["Threshold"] == 4.0 * 1073741824
        storage_call = [c for c in put_calls if c.kwargs["MetricName"] == "FreeLocalStorage"][0]
        assert storage_call.kwargs["Threshold"] == 20.0 * 1073741824

    def test_create_aurora_rds_replica_lag_stat_and_comparison(self):
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-006"
        tags = {
            "Monitoring": "on", "Name": "my-aurora",
            "_is_cluster_writer": "true", "_has_readers": "true", "_is_serverless_v2": "false",
        }
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource(db_id, "AuroraRDS", tags)

        put_calls = mock_cw.put_metric_alarm.call_args_list
        lag_call = [c for c in put_calls if c.kwargs["MetricName"] == "AuroraReplicaLagMaximum"][0]
        assert lag_call.kwargs["Statistic"] == "Maximum"
        assert lag_call.kwargs["ComparisonOperator"] == "GreaterThanThreshold"
        assert lag_call.kwargs["Threshold"] == 2000000.0

    def test_dynamic_alarm_for_aurora_rds(self):
        mock_cw = self._make_mock_cw()
        mock_cw.list_metrics.return_value = {
            "Metrics": [{
                "Namespace": "AWS/RDS",
                "MetricName": "CommitLatency",
                "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "aurora-db-007"}],
            }]
        }
        db_id = "aurora-db-007"
        tags = {
            "Monitoring": "on", "Name": "my-aurora",
            "Threshold_CommitLatency": "500",
        }
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(db_id, "AuroraRDS", tags)

        assert len(created) == 6
        assert any("CommitLatency" in n for n in created)


# ──────────────────────────────────────────────
# VPN treat_missing_data 알람 생성 테스트
# ──────────────────────────────────────────────

class TestTreatMissingDataAndOpenSearchDimension:
    """VPN treat_missing_data=breaching 검증.
    Validates: Requirements 2.3
    """

    @staticmethod
    def _mock_cw():
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_vpn_alarm_treat_missing_data_breaching(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Name": "my-vpn"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("vpn-001", "VPN", tags)

        assert len(created) == 1
        call = mock_cw.put_metric_alarm.call_args_list[0]
        assert call.kwargs["TreatMissingData"] == "breaching"

    def test_non_vpn_alarm_treat_missing_data_missing(self):
        mock_cw = self._mock_cw()
        tags = {"Monitoring": "on", "Name": "my-func"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("my-func", "Lambda", tags)

        assert len(created) == 2
        for call in mock_cw.put_metric_alarm.call_args_list:
            assert call.kwargs["TreatMissingData"] == "missing"
