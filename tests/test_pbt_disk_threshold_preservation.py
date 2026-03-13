"""
Preservation Property Tests - Non-disk metric and default fallback behavior

Property 2: Preservation - Verify sync_alarms_for_resource preserves
non-disk metric handling, default fallback, and recreate trigger behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

EXPECTED: These tests PASS on unfixed code to establish baseline behavior.
"""

import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import sync_alarms_for_resource

# EC2 alarm_defs iterate in order: CPU, Memory, Disk
# Non-disk branch calls describe_alarms(AlarmNames=metric_alarms[:1])
# Disk branch calls describe_alarms(AlarmNames=disk_alarms)

non_disk_metrics = st.sampled_from(["CPU", "Memory"])
threshold_values = st.integers(min_value=1, max_value=100)
_DISPLAY = {"CPU": "CPUUtilization", "Memory": "mem_used_percent"}
_ENV = {"ENVIRONMENT": "prod", "SNS_TOPIC_ARN_ALERT": ""}


def _metric_alarm(iid, metric, threshold):
    display = _DISPLAY[metric]
    return f"[EC2] srv {display} >{int(threshold)}% ({iid})"


def _disk_alarm(iid, path="/", threshold=80):
    return f"[EC2] srv disk_used_percent({path}) >{int(threshold)}% ({iid})"


class TestNonDiskMetricPreservation:
    """For CPU/Memory metrics, matching threshold should be ok. Validates: Requirements 3.2"""

    @given(metric=non_disk_metrics, threshold=threshold_values)
    @settings(max_examples=50)
    def test_non_disk_alarm_with_matching_threshold_is_ok(self, metric, threshold):
        """**Validates: Requirements 3.2**"""
        iid = "i-preserve01"
        # Build all three alarm names (CPU, Memory, Disk all present)
        cpu_name = _metric_alarm(iid, "CPU", threshold if metric == "CPU" else 80)
        mem_name = _metric_alarm(iid, "Memory", threshold if metric == "Memory" else 80)
        disk_name = _disk_alarm(iid)
        target_name = _metric_alarm(iid, metric, threshold)

        tags = {
            "Monitoring": "on",
            "Name": "srv",
            f"Threshold_{metric}": str(threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        # describe_alarms call order: CPU, Memory, Disk
        cpu_thr = float(threshold) if metric == "CPU" else 80.0
        mem_thr = float(threshold) if metric == "Memory" else 80.0
        mock_cw.describe_alarms.side_effect = [
            # CPU branch
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": cpu_thr}]},
            # Memory branch
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": mem_thr}]},
            # Disk branch
            {"MetricAlarms": [{"AlarmName": disk_name, "Threshold": 80.0,
             "Dimensions": [{"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"}]}]},
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]), \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        assert target_name in result["ok"], (
            f"Expected '{target_name}' in ok but got: "
            f"ok={result['ok']}, updated={result['updated']}, created={result['created']}"
        )


class TestDefaultFallbackPreservation:
    """Disk alarms with no path-specific tags use default 80. Validates: Requirements 3.1"""

    @given(data=st.data())
    @settings(max_examples=30)
    def test_disk_alarm_default_threshold_is_ok(self, data):
        """**Validates: Requirements 3.1**"""
        iid = "i-fallback01"
        cpu_name = _metric_alarm(iid, "CPU", 80)
        mem_name = _metric_alarm(iid, "Memory", 80)
        disk_name = _disk_alarm(iid)

        # No Threshold_Disk_* tags -> default 80 fallback
        tags = {"Monitoring": "on", "Name": "srv"}

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        # describe_alarms call order: CPU, Memory, Disk
        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": 80.0}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": 80.0}]},
            {"MetricAlarms": [{"AlarmName": disk_name, "Threshold": 80.0,
             "Dimensions": [{"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"}]}]},
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]), \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        assert disk_name in result["ok"], (
            f"Expected '{disk_name}' in ok but got: "
            f"ok={result['ok']}, updated={result['updated']}"
        )


class TestNoDiskAlarmsTriggersRecreate:
    """Missing disk alarms triggers create_alarms_for_resource. Validates: Requirements 3.4"""

    @given(cpu_threshold=threshold_values)
    @settings(max_examples=30)
    def test_missing_disk_alarms_triggers_create(self, cpu_threshold):
        """**Validates: Requirements 3.4**"""
        iid = "i-nodisk01"
        cpu_name = _metric_alarm(iid, "CPU", cpu_threshold)
        mem_name = _metric_alarm(iid, "Memory", 80)

        tags = {
            "Monitoring": "on",
            "Name": "srv",
            "Threshold_CPU": str(cpu_threshold),
        }

        # Only CPU and Memory alarms - no disk_used_percent
        existing_alarms = [cpu_name, mem_name]
        mock_cw = MagicMock()

        # describe_alarms call order: CPU, Memory (Disk branch skips - no disk alarms found)
        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(cpu_threshold)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": 80.0}]},
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=["new"]) as mock_create, \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        mock_create.assert_called_once_with(iid, "EC2", tags)
