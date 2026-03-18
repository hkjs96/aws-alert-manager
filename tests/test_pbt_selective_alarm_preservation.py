"""
Preservation Property Tests - 변경되지 않은 알람 및 최초 생성 동작 유지

Property 2 (Preservation): sync_alarms_for_resource에서 버그 조건이 성립하지 않는 경우
(최초 생성, 모든 알람 일치) 기존 동작이 그대로 유지되어야 함.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

EXPECTED: These tests PASS on unfixed code to establish baseline behavior.
"""

import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import sync_alarms_for_resource

_ENV = {"ENVIRONMENT": "prod", "SNS_TOPIC_ARN_ALERT": ""}

threshold_values = st.integers(min_value=1, max_value=100)


def _cpu_alarm(iid: str, threshold: int) -> str:
    return f"[EC2] srv CPUUtilization >{threshold}% ({iid})"


def _mem_alarm(iid: str, threshold: int) -> str:
    return f"[EC2] srv mem_used_percent >{threshold}% ({iid})"


def _disk_alarm(iid: str, path: str, threshold: int) -> str:
    return f"[EC2] srv disk_used_percent({path}) >{threshold}% ({iid})"


class TestInitialCreationPreservation:
    """
    알람이 없을 때 create_alarms_for_resource 전체 호출 동작 유지.
    Validates: Requirements 3.1
    """

    @given(data=st.data())
    @settings(max_examples=30)
    def test_no_existing_alarms_calls_create_alarms(self, data):
        """
        **Property 2: Preservation** - 최초 생성 시 create_alarms_for_resource 호출 유지

        알람이 하나도 없을 때 create_alarms_for_resource 전체 호출이 유지되어야 함.

        **Validates: Requirements 3.1**
        """
        iid = "i-preserve001"
        tags = {"Monitoring": "on", "Name": "srv"}

        with patch("common.alarm_manager._get_cw_client", return_value=MagicMock()), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[]), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=["alarm1"]) as mock_create, \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        mock_create.assert_called_once_with(iid, "EC2", tags)


class TestAllAlarmsOkPreservation:
    """
    모든 알람 임계치가 일치할 때 아무 동작도 하지 않는 동작 유지.
    Validates: Requirements 3.2
    """

    @given(cpu_thr=threshold_values, mem_thr=threshold_values)
    @settings(max_examples=50)
    def test_all_alarms_ok_no_delete_or_recreate(self, cpu_thr, mem_thr):
        """
        **Property 2: Preservation** - 모든 알람 일치 시 아무 동작 없음

        result["ok"]만 존재할 때 어떤 알람도 삭제하거나 재생성하지 않아야 함.

        **Validates: Requirements 3.2**
        """
        iid = "i-preserve002"
        cpu_name = _cpu_alarm(iid, cpu_thr)
        mem_name = _mem_alarm(iid, mem_thr)
        disk_name = _disk_alarm(iid, "/", 80)

        tags = {
            "Monitoring": "on",
            "Name": "srv",
            "Threshold_CPU": str(cpu_thr),
            "Threshold_Memory": str(mem_thr),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(cpu_thr)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": float(mem_thr)}]},
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_name,
                        "Threshold": 80.0,
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"},
                        ],
                    }
                ]
            },
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]) as mock_create, \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        # 아무 삭제/재생성도 발생하지 않아야 함
        mock_cw.delete_alarms.assert_not_called()
        mock_cw.put_metric_alarm.assert_not_called()
        mock_create.assert_not_called()
        assert result["updated"] == [], f"updated가 비어있지 않음: {result['updated']}"
        assert result["created"] == [], f"created가 비어있지 않음: {result['created']}"


class TestOkAlarmsPreservedAfterSync:
    """
    result["ok"] 알람은 sync 후에도 그대로 유지되어야 함.
    Validates: Requirements 3.3
    """

    @given(cpu_thr=threshold_values)
    @settings(max_examples=30)
    def test_ok_alarms_in_result_when_all_match(self, cpu_thr):
        """
        **Property 2: Preservation** - result["ok"] 알람 목록 정확성

        모든 알람 임계치가 일치할 때 result["ok"]에 모든 알람이 포함되어야 함.

        **Validates: Requirements 3.3**
        """
        iid = "i-preserve003"
        cpu_name = _cpu_alarm(iid, cpu_thr)
        mem_name = _mem_alarm(iid, 80)
        disk_name = _disk_alarm(iid, "/", 80)

        tags = {
            "Monitoring": "on",
            "Name": "srv",
            "Threshold_CPU": str(cpu_thr),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(cpu_thr)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": 80.0}]},
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_name,
                        "Threshold": 80.0,
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"},
                        ],
                    }
                ]
            },
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]), \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        assert cpu_name in result["ok"], (
            f"CPU 알람 '{cpu_name}'이 result['ok']에 없음: {result}"
        )
        assert mem_name in result["ok"], (
            f"Memory 알람 '{mem_name}'이 result['ok']에 없음: {result}"
        )
        assert disk_name in result["ok"], (
            f"Disk 알람 '{disk_name}'이 result['ok']에 없음: {result}"
        )


class TestCreateAlarmsForResourceUnchanged:
    """
    create_alarms_for_resource 함수 자체는 변경되지 않아야 함.
    직접 호출 시 _delete_all_alarms_for_resource 호출 동작 유지.
    Validates: Requirements 3.4
    """

    def test_create_alarms_still_deletes_all_first(self):
        """
        **Property 2: Preservation** - create_alarms_for_resource 불변 보존

        create_alarms_for_resource 직접 호출 시 _delete_all_alarms_for_resource가
        먼저 호출되는 기존 동작이 유지되어야 함.

        **Validates: Requirements 3.4**
        """
        from common.alarm_manager import create_alarms_for_resource

        iid = "i-preserve004"
        tags = {"Monitoring": "on", "Name": "srv"}
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._delete_all_alarms_for_resource") as mock_delete_all, \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=["old-alarm"]), \
             patch.dict(os.environ, _ENV):
            create_alarms_for_resource(iid, "EC2", tags)

        mock_delete_all.assert_called_once_with(iid)
