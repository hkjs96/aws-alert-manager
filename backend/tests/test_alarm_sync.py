"""
동기화 + 동적 알람 + off 삭제 테스트

sync_alarms_for_resource() 동기화 로직, 동적 알람 생성/삭제/업데이트,
Threshold_*=off 시 기존 알람 삭제 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from common.alarm_manager import (
    create_alarms_for_resource,
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
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[]):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["created"]) > 0

    def test_matching_threshold_is_ok(self):
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
        ]

        def _make_desc(metric_key):
            meta = json.dumps({"metric_key": metric_key, "resource_id": "i-001", "resource_type": "EC2"}, separators=(",", ":"))
            return f"Auto-created | {meta}"

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": "StatusCheckFailed" if "StatusCheckFailed" in n else ("disk_used_percent" if "disk" in n else "CPUUtilization"),
                    "AlarmDescription": _make_desc(mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["ok"]) == 4
        assert result["created"] == []
        assert result["updated"] == []

    def test_mismatched_threshold_gets_updated(self):
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization > 70% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
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
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert len(result["updated"]) > 0

    def test_legacy_elb_alarm_migrated_to_alb(self):
        """기존 [ELB] 알람이 threshold 불일치 시 [ALB] 알람으로 재생성."""
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        legacy_name = f"[ELB] my-alb RequestCount > 5000 (TagName: {alb_arn})"

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

        tags = {"Monitoring": "on", "Name": "my-alb", "Threshold_RequestCount": "8000"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[legacy_name]):
            result = sync_alarms_for_resource(alb_arn, "ALB", tags)

        assert legacy_name in result["updated"]
        put_calls = mock_cw.put_metric_alarm.call_args_list
        assert len(put_calls) > 0
        recreated_name = put_calls[0].kwargs.get("AlarmName", "")
        assert recreated_name.startswith("[ALB] "), f"Expected [ALB] prefix, got: {recreated_name}"


# ──────────────────────────────────────────────
# 동적 알람 생성/삭제/업데이트
# ──────────────────────────────────────────────

class TestSyncDynamicAlarms:
    """sync_alarms_for_resource()에서 동적 알람 생성/삭제/업데이트 검증."""

    @staticmethod
    def _make_desc(metric_key, resource_id="i-001", resource_type="EC2"):
        import json
        meta = json.dumps(
            {"metric_key": metric_key, "resource_id": resource_id,
             "resource_type": resource_type},
            separators=(",", ":"),
        )
        return f"Auto-created | {meta}"

    def test_new_dynamic_tag_creates_alarm(self):
        """Validates: Requirements 5.1, 5.2"""
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr,
                    "MetricName": n.split()[2] if len(n.split()) > 2 else "unknown",
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}

        tags = {"Threshold_NetworkIn": "1000000"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert any("NetworkIn" in n for n in result["created"])

    def test_removed_dynamic_tag_deletes_alarm(self):
        """Validates: Requirements 6.1, 6.2"""
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn > 1000000 (TagName: i-001)"
        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr, "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        tags = {}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert "deleted" in result
        assert dynamic_alarm_name in result["deleted"]

    def test_dynamic_threshold_changed_updates_alarm(self):
        """Validates: Requirements 7.1, 7.3"""
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn > 1000000 (TagName: i-001)"
        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr, "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.delete_alarms.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}

        tags = {"Threshold_NetworkIn": "2000000"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert dynamic_alarm_name in result["updated"]

    def test_dynamic_threshold_same_is_ok(self):
        """Validates: Requirements 7.2"""
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn > 1000000 (TagName: i-001)"
        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr, "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        tags = {"Threshold_NetworkIn": "1000000"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert dynamic_alarm_name in result["ok"]


# ──────────────────────────────────────────────
# sync 하드코딩 off 삭제
# ──────────────────────────────────────────────

class TestSyncHardcodedOffDeletion:
    """sync_alarms_for_resource()에서 Threshold_*=off 시 기존 알람 삭제 검증."""

    @staticmethod
    def _make_desc(metric_key, resource_id="i-001", resource_type="EC2"):
        import json
        meta = json.dumps(
            {"metric_key": metric_key, "resource_id": resource_id,
             "resource_type": resource_type},
            separators=(",", ":"),
        )
        return f"Auto-created | {meta}"

    def test_off_tag_deletes_existing_hardcoded_alarm(self):
        """Validates: Requirements 3.2, 4.2"""
        mock_cw = MagicMock()
        cpu_alarm_name = "[EC2] srv CPUUtilization > 80% (TagName: i-001)"
        existing = [
            cpu_alarm_name,
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr, "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        tags = {"Threshold_CPU": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert "deleted" in result
        assert cpu_alarm_name in result["deleted"]

    def test_off_deletion_logged(self):
        """Validates: Requirements 4.3"""
        import logging
        mock_cw = MagicMock()
        cpu_alarm_name = "[EC2] srv CPUUtilization > 80% (TagName: i-001)"
        existing = [
            cpu_alarm_name,
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n, "Threshold": thr, "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk), "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        tags = {"Threshold_CPU": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing), \
             patch("common.alarm_manager.logger") as mock_logger, \
             patch("common.alarm_sync.logger", mock_logger):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert cpu_alarm_name in result["deleted"]
        log_messages = [
            str(call) for call in mock_logger.info.call_args_list
        ]
        assert any("off" in msg.lower() or "delet" in msg.lower() for msg in log_messages)


# ──────────────────────────────────────────────
# create_alarms_for_resource() off 체크
# ──────────────────────────────────────────────

class TestCreateAlarmsOffCheck:
    """create_alarms_for_resource()에서 Threshold_*=off 태그 설정 시 해당 알람 스킵 검증.
    Validates: Requirements 3.1, 3.3, 4.1
    """

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

    def test_cpu_off_skips_cpu_alarm(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server", "Threshold_CPU": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        assert len(created) == 3

    def test_disk_root_off_skips_root_disk_alarm(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server", "Threshold_Disk_root": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("disk_used_percent" in n for n in created)
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        assert len(created) == 3

    def test_non_off_metrics_created_normally(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert len(created) == 4

    def test_off_case_insensitive(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "OFF"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert len(created) == 3

    def test_multiple_off_metrics(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "off", "Threshold_Memory": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert not any("mem_used_percent" in n for n in created)
        assert len(created) == 2

    def test_rds_off_metric_skipped(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Threshold_CPU": "off"}
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert len(created) == 6
