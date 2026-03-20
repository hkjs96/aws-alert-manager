"""
alarm_manager 단위 테스트

CloudWatch Alarm 자동 생성/삭제/동기화 기능 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from common.alarm_manager import (
    _alarm_name,
    _build_alarm_description,
    _create_dynamic_alarm,
    _extract_elb_dimension,
    _get_alarm_defs,
    _parse_alarm_metadata,
    _parse_threshold_tags,
    _pretty_alarm_name,
    _resolve_metric_dimensions,
    _find_alarms_for_resource,
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    import common.alarm_manager as am
    am._get_cw_client.cache_clear()
    yield
    am._get_cw_client.cache_clear()


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

    def test_pretty_alarm_name_always_within_255_chars(self):
        long_name = "a" * 256
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith("(i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_label_first(self):
        long_name = "my-very-long-server-name-" * 10  # 250 chars
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert "CPUUtilization" in name  # display_metric preserved
        assert name.endswith("(i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_display_metric_when_label_insufficient(self):
        # Very long resource_id leaves little room
        long_id = "i-" + "a" * 200
        name = _pretty_alarm_name("EC2", long_id, "srv", "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"({long_id})")

    def test_pretty_alarm_name_preserves_resource_id_always(self):
        long_id = "i-" + "x" * 150
        long_name = "n" * 200
        name = _pretty_alarm_name("EC2", long_id, long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"({long_id})")

    def test_pretty_alarm_name_short_inputs_unchanged(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "CPU", 80)
        assert name == "[RDS] my-db CPUUtilization >80% (db-001)"
        assert len(name) <= 255

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
        assert defs == []

    def test_get_alarm_defs_unknown(self):
        assert _get_alarm_defs("UNKNOWN") == []

    # ── Task 3.1: ALB/NLB/TG 알람 정의 분리 검증 ──

    def test_get_alarm_defs_alb(self):
        """_get_alarm_defs('ALB') → RequestCount (AWS/ApplicationELB) 반환.
        Validates: Requirements 4.1
        """
        defs = _get_alarm_defs("ALB")
        assert len(defs) == 1
        assert defs[0]["metric"] == "RequestCount"
        assert defs[0]["namespace"] == "AWS/ApplicationELB"
        assert defs[0]["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_nlb(self):
        """_get_alarm_defs('NLB') → ProcessedBytes, ActiveFlowCount, NewFlowCount (AWS/NetworkELB) 반환.
        Validates: Requirements 4.2
        """
        defs = _get_alarm_defs("NLB")
        assert len(defs) == 3
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount"}
        for d in defs:
            assert d["namespace"] == "AWS/NetworkELB"
            assert d["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_tg(self):
        """_get_alarm_defs('TG') → RequestCount, HealthyHostCount 반환.
        Validates: Requirements 4.3
        """
        defs = _get_alarm_defs("TG")
        assert len(defs) == 2
        metrics = {d["metric"] for d in defs}
        assert metrics == {"RequestCount", "HealthyHostCount"}
        for d in defs:
            assert d["dimension_key"] == "TargetGroup"

    def test_get_alarm_defs_elb_removed(self):
        """_get_alarm_defs('ELB') → 빈 리스트 반환 (제거됨).
        Validates: Requirements 7.2
        """
        defs = _get_alarm_defs("ELB")
        assert defs == []

    def test_hardcoded_metric_keys_alb_nlb_tg(self):
        """_HARDCODED_METRIC_KEYS에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.2
        """
        from common.alarm_manager import _HARDCODED_METRIC_KEYS
        assert "ALB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["ALB"] == {"RequestCount"}
        assert "NLB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["NLB"] == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount"}
        assert "TG" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["TG"] == {"RequestCount", "HealthyHostCount"}
        assert "ELB" not in _HARDCODED_METRIC_KEYS

    def test_namespace_map_alb_nlb_tg(self):
        """_NAMESPACE_MAP에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.3
        """
        from common.alarm_manager import _NAMESPACE_MAP
        assert _NAMESPACE_MAP["ALB"] == ["AWS/ApplicationELB"]
        assert _NAMESPACE_MAP["NLB"] == ["AWS/NetworkELB"]
        assert _NAMESPACE_MAP["TG"] == ["AWS/ApplicationELB", "AWS/NetworkELB"]
        assert "ELB" not in _NAMESPACE_MAP

    def test_dimension_key_map_alb_nlb_tg(self):
        """_DIMENSION_KEY_MAP에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.4
        """
        from common.alarm_manager import _DIMENSION_KEY_MAP
        assert _DIMENSION_KEY_MAP["ALB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["NLB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["TG"] == "TargetGroup"
        assert "ELB" not in _DIMENSION_KEY_MAP


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

    def test_alb_extracts_dimension_from_arn(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(arn, "ALB", {"Monitoring": "on"})

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

    def test_find_alarms_deduplicates_legacy_and_new_format(self):
        """레거시와 새 포맷 검색 결과가 중복되지 않는지 확인."""
        mock_cw = MagicMock()
        # Same alarm found by both legacy prefix and new format prefix
        shared_alarm = {"AlarmName": "i-001-CPU-prod"}
        new_alarm = {"AlarmName": "[EC2] srv CPUUtilization >80% (i-001)"}
        mock_paginator = MagicMock()
        # Call 1 (legacy prefix=i-001): returns shared_alarm
        # Call 2 (new prefix=[EC2] ): returns shared_alarm + new_alarm
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": [shared_alarm]}],
            [{"MetricAlarms": [shared_alarm, new_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        # shared_alarm should appear only once
        assert result.count("i-001-CPU-prod") == 1
        assert "[EC2] srv CPUUtilization >80% (i-001)" in result
        assert len(result) == 2

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

    def test_find_alarms_alb_also_searches_elb_prefix(self):
        """resource_type='ALB'일 때 [ELB] prefix 알람도 검색되는지 확인."""
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        legacy_alarm = {"AlarmName": f"[ELB] my-alb RequestCount >5000 ({alb_arn})"}
        new_alarm = {"AlarmName": f"[ALB] my-alb RequestCount >5000 ({alb_arn})"}
        mock_paginator = MagicMock()
        # Call 1: legacy prefix (alb_arn) → empty
        # Call 2: [ALB] prefix → new_alarm
        # Call 3: [ELB] prefix → legacy_alarm
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],           # legacy prefix search
            [{"MetricAlarms": [new_alarm]}],   # [ALB] prefix search
            [{"MetricAlarms": [legacy_alarm]}], # [ELB] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert new_alarm["AlarmName"] in result
        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 2

    def test_find_alarms_nlb_also_searches_elb_prefix(self):
        """resource_type='NLB'일 때 [ELB] prefix 알람도 검색되는지 확인."""
        mock_cw = MagicMock()
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        legacy_alarm = {"AlarmName": f"[ELB] my-nlb ProcessedBytes >1000 ({nlb_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],            # legacy prefix search
            [{"MetricAlarms": []}],            # [NLB] prefix search
            [{"MetricAlarms": [legacy_alarm]}], # [ELB] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(nlb_arn, "NLB")

        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 1

    def test_find_alarms_ec2_does_not_search_elb_prefix(self):
        """resource_type='EC2'일 때 [ELB] prefix를 추가 검색하지 않는지 확인."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],  # legacy prefix search
            [{"MetricAlarms": []}],  # [EC2] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        assert result == []
        # EC2는 legacy + [EC2] = 2번만 paginate 호출
        assert mock_paginator.paginate.call_count == 2


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
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
        ]

        def _make_desc(metric_key):
            meta = json.dumps({"metric_key": metric_key, "resource_id": "i-001", "resource_type": "EC2"}, separators=(",", ":"))
            return f"Auto-created | {meta}"

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk = "CPU"
                elif "mem_used_percent" in n:
                    mk = "Memory"
                else:
                    mk = "Disk_root"
                alarms.append({
                    "AlarmName": n,
                    "Threshold": 80.0,
                    "MetricName": "disk_used_percent" if "disk" in n else "CPUUtilization",
                    "AlarmDescription": _make_desc(mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["ok"]) == 3
        assert result["created"] == []
        assert result["updated"] == []

    def test_mismatched_threshold_gets_updated(self):
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >70% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
        ]

        def _make_desc(metric_key):
            meta = json.dumps({"metric_key": metric_key, "resource_id": "i-001", "resource_type": "EC2"}, separators=(",", ":"))
            return f"Auto-created | {meta}"

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 70.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": "disk_used_percent" if "disk" in n else "CPUUtilization",
                    "AlarmDescription": _make_desc(mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert len(result["updated"]) > 0

    def test_legacy_elb_alarm_migrated_to_alb(self):
        """기존 [ELB] 알람이 threshold 불일치 시 [ALB] 알람으로 재생성."""
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        legacy_name = f"[ELB] my-alb RequestCount >5000 ({alb_arn})"

        # 레거시 알람: MetricName 기반 폴백으로 metric_key="RequestCount" 매칭
        # threshold 불일치 → updated → _recreate_alarm_by_name → 새 [ALB] prefix
        def describe_side_effect(**kwargs):
            return {"MetricAlarms": [{
                "AlarmName": legacy_name,
                "Threshold": 5000.0,
                "MetricName": "RequestCount",
                "AlarmDescription": "Legacy alarm without metadata",
                "Dimensions": [],
            }]}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        # Threshold_RequestCount=8000 태그로 threshold 불일치 유도
        tags = {"Monitoring": "on", "Name": "my-alb", "Threshold_RequestCount": "8000"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[legacy_name]):
            result = sync_alarms_for_resource(alb_arn, "ALB", tags)

        # threshold 불일치 → updated
        assert legacy_name in result["updated"]
        # put_metric_alarm이 [ALB] prefix 알람 이름으로 호출되었는지 확인
        put_calls = mock_cw.put_metric_alarm.call_args_list
        assert len(put_calls) > 0
        recreated_name = put_calls[0].kwargs.get("AlarmName", "")
        assert recreated_name.startswith("[ALB] "), f"Expected [ALB] prefix, got: {recreated_name}"


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
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {"Name": "srv"})

        # 모든 put_metric_alarm 호출에 JSON 메타데이터가 포함되어야 함
        for call in mock_cw.put_metric_alarm.call_args_list:
            desc = call.kwargs["AlarmDescription"]
            meta = _parse_alarm_metadata(desc)
            assert meta is not None, f"Missing JSON metadata in: {desc}"
            assert meta["resource_id"] == "i-001"
            assert meta["resource_type"] == "EC2"
            assert "metric_key" in meta

    def test_roundtrip_build_and_parse(self):
        """build → parse 라운드트립 검증."""
        desc = _build_alarm_description("RDS", "db-001", "FreeMemoryGB", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["metric_key"] == "FreeMemoryGB"
        assert meta["resource_id"] == "db-001"
        assert meta["resource_type"] == "RDS"


# ──────────────────────────────────────────────
# _parse_threshold_tags 테스트
# ──────────────────────────────────────────────

class TestParseThresholdTags:

    def test_extracts_dynamic_metric_for_ec2(self):
        """하드코딩 목록에 없는 메트릭을 추출."""
        tags = {"Threshold_NetworkIn": "1000000", "Threshold_CPU": "90"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "NetworkIn" in result
        assert result["NetworkIn"] == 1000000.0
        # CPU는 하드코딩 목록에 있으므로 제외
        assert "CPU" not in result

    def test_extracts_dynamic_metric_for_rds(self):
        tags = {"Threshold_ReadLatency": "0.01", "Threshold_FreeMemoryGB": "4"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "ReadLatency" in result
        assert result["ReadLatency"] == 0.01
        assert "FreeMemoryGB" not in result

    def test_skips_disk_prefix_tags(self):
        """Threshold_Disk_* 패턴은 기존 Disk 로직에서 처리하므로 제외."""
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
        long_key = "Threshold_" + "A" * 119  # 129 chars total
        tags = {long_key: "100"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_accepts_tag_key_at_128_chars(self):
        metric = "A" * 118  # Threshold_ (10) + 118 = 128
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


# ──────────────────────────────────────────────
# _resolve_metric_dimensions 테스트
# ──────────────────────────────────────────────

class TestResolveMetricDimensions:

    def test_resolves_ec2_metric(self):
        """EC2 메트릭의 네임스페이스/디멘션 해석."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is not None
        namespace, dims = result
        assert namespace in ("AWS/EC2", "CWAgent")
        assert any(d["Name"] == "InstanceId" for d in dims)

    def test_returns_none_when_metric_not_found(self):
        """메트릭이 없으면 None 반환."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NonExistent", "EC2")

        assert result is None

    def test_resolves_rds_metric(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "db-001"}]}
        ]}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("db-001", "ReadLatency", "RDS")

        assert result is not None
        namespace, dims = result
        assert namespace == "AWS/RDS"

    def test_elb_uses_arn_suffix_as_dimension(self):
        """ALB/NLB/TG는 ARN suffix를 디멘션 값으로 사용."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "LoadBalancer", "Value": "app/my-alb/abc"}]}
        ]}
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions(arn, "ProcessedBytes", "ALB")

        assert result is not None

    def test_client_error_returns_none(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "fail"}}, "ListMetrics"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is None


# ──────────────────────────────────────────────
# _create_dynamic_alarm 테스트
# ──────────────────────────────────────────────

class TestCreateDynamicAlarm:

    def test_creates_alarm_when_metric_resolved(self):
        """list_metrics로 해석된 메트릭에 대해 알람 생성."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
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
        """메트릭이 해석되지 않으면 알람 미생성."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NonExistent", 100.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert created == []
        mock_cw.put_metric_alarm.assert_not_called()

    def test_alarm_name_within_255_chars(self):
        """동적 알람 이름이 255자 이내."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        long_name = "x" * 200
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
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
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "srv",
                "NetworkIn", 100.0, mock_cw, "", created,
            )

        assert created == []
