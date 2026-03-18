"""
Bug Condition Exploration Test - 변경된 알람만 개별 삭제·재생성

Property 1 (Fault Condition): sync_alarms_for_resource에서 needs_recreate=True 시
create_alarms_for_resource 전체를 호출하여 result["ok"] 알람까지 삭제되는 버그.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.3**

EXPECTED: These tests FAIL on unfixed code because sync calls
create_alarms_for_resource → _delete_all_alarms_for_resource, deleting ALL alarms
including result["ok"] alarms that should be preserved.
"""

import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import sync_alarms_for_resource

_ENV = {"ENVIRONMENT": "prod", "SNS_TOPIC_ARN_ALERT": ""}

# 변경 가능한 임계치 (기본값 80과 다른 값)
non_default_thresholds = st.integers(min_value=1, max_value=99).filter(lambda x: x != 80)

# 변경되지 않는 알람 임계치 (기본값 80 유지)
ok_threshold = 80


def _cpu_alarm(iid: str, threshold: int) -> str:
    return f"[EC2] test-server CPUUtilization >{threshold}% ({iid})"


def _mem_alarm(iid: str, threshold: int) -> str:
    return f"[EC2] test-server mem_used_percent >{threshold}% ({iid})"


def _disk_alarm(iid: str, path: str, threshold: int) -> str:
    return f"[EC2] test-server disk_used_percent({path}) >{threshold}% ({iid})"


class TestSelectiveAlarmFaultCondition:
    """
    needs_recreate=True 시 result["ok"] 알람이 삭제되지 않아야 함.

    BUG: sync calls create_alarms_for_resource → _delete_all_alarms_for_resource,
    which deletes ALL alarms including result["ok"] alarms.
    """

    @given(new_disk_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_ok_alarms_not_deleted_when_disk_threshold_changes(self, new_disk_threshold):
        """
        **Property 1: Fault Condition** - 변경된 알람만 개별 삭제·재생성

        Disk_data 임계치 변경 시 CPU/Memory/Disk_root 알람(result["ok"])은
        삭제되지 않아야 한다.

        **Validates: Requirements 1.1, 2.1, 2.3**
        """
        iid = "i-fault001"
        cpu_name = _cpu_alarm(iid, ok_threshold)
        mem_name = _mem_alarm(iid, ok_threshold)
        disk_root_name = _disk_alarm(iid, "/", ok_threshold)
        disk_data_name = _disk_alarm(iid, "/data", new_disk_threshold)

        # Disk_data 임계치만 변경
        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_Disk_root": str(ok_threshold),
            "Threshold_Disk_data": str(new_disk_threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_root_name, disk_data_name]
        mock_cw = MagicMock()

        # describe_alarms: CPU(ok), Memory(ok), Disk(root=ok, data=changed)
        # + _recreate_alarm_by_name에서 disk_data 알람 describe 1회 추가
        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(ok_threshold)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": float(ok_threshold)}]},
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_root_name,
                        "Threshold": float(ok_threshold),
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"},
                            {"Name": "device", "Value": "xvda1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    },
                    {
                        "AlarmName": disk_data_name,
                        "Threshold": float(new_disk_threshold),
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/data"},
                            {"Name": "device", "Value": "xvdb1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    },
                ]
            },
            # _recreate_alarm_by_name(disk_data_name) 내부 describe_alarms 호출
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_data_name,
                        "MetricName": "disk_used_percent",
                        "Threshold": float(new_disk_threshold),
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/data"},
                            {"Name": "device", "Value": "xvdb1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    }
                ]
            },
        ]

        deleted_alarms = []

        def mock_delete_alarms(AlarmNames):
            deleted_alarms.extend(AlarmNames)

        mock_cw.delete_alarms.side_effect = lambda **kwargs: mock_delete_alarms(
            kwargs.get("AlarmNames", [])
        )

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        # result["ok"] 알람은 삭제되지 않아야 함
        assert cpu_name not in deleted_alarms, (
            f"CPU 알람 '{cpu_name}'이 삭제됨. "
            f"result['ok'] 알람은 삭제되지 않아야 함. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert mem_name not in deleted_alarms, (
            f"Memory 알람 '{mem_name}'이 삭제됨. "
            f"result['ok'] 알람은 삭제되지 않아야 함. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert disk_root_name not in deleted_alarms, (
            f"Disk_root 알람 '{disk_root_name}'이 삭제됨. "
            f"result['ok'] 알람은 삭제되지 않아야 함. "
            f"삭제된 알람: {deleted_alarms}"
        )

    @given(new_cpu_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_ok_alarms_not_deleted_when_cpu_threshold_changes(self, new_cpu_threshold):
        """
        **Property 1: Fault Condition** - CPU 임계치 변경 시 Memory/Disk 알람 보존

        CPU 임계치 변경 시 Memory/Disk 알람(result["ok"])은 삭제되지 않아야 한다.

        **Validates: Requirements 1.1, 2.1, 2.3**
        """
        iid = "i-fault002"
        cpu_name = _cpu_alarm(iid, new_cpu_threshold)
        mem_name = _mem_alarm(iid, ok_threshold)
        disk_name = _disk_alarm(iid, "/", ok_threshold)

        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_CPU": str(new_cpu_threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        mock_cw.describe_alarms.side_effect = [
            # CPU: 임계치 변경됨 (new_cpu_threshold != ok_threshold)
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(ok_threshold)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": float(ok_threshold)}]},
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_name,
                        "Threshold": float(ok_threshold),
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/"},
                            {"Name": "device", "Value": "xvda1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    }
                ]
            },
            # _recreate_alarm_by_name(cpu_name) 내부 describe_alarms 호출
            {
                "MetricAlarms": [
                    {
                        "AlarmName": cpu_name,
                        "MetricName": "CPUUtilization",
                        "Threshold": float(ok_threshold),
                        "Dimensions": [{"Name": "InstanceId", "Value": iid}],
                    }
                ]
            },
        ]

        deleted_alarms = []

        def mock_delete_alarms(AlarmNames):
            deleted_alarms.extend(AlarmNames)

        mock_cw.delete_alarms.side_effect = lambda **kwargs: mock_delete_alarms(
            kwargs.get("AlarmNames", [])
        )

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch.dict(os.environ, _ENV):
            result = sync_alarms_for_resource(iid, "EC2", tags)

        # Memory/Disk 알람은 삭제되지 않아야 함
        assert mem_name not in deleted_alarms, (
            f"Memory 알람 '{mem_name}'이 삭제됨. "
            f"result['ok'] 알람은 삭제되지 않아야 함. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert disk_name not in deleted_alarms, (
            f"Disk 알람 '{disk_name}'이 삭제됨. "
            f"result['ok'] 알람은 삭제되지 않아야 함. "
            f"삭제된 알람: {deleted_alarms}"
        )

    @given(new_disk_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_delete_all_not_called_on_partial_update(self, new_disk_threshold):
        """
        **Property 1: Fault Condition** - _delete_all_alarms_for_resource 미호출 확인

        needs_recreate=True 시 _delete_all_alarms_for_resource가 호출되지 않아야 함.

        **Validates: Requirements 1.2, 2.1**
        """
        iid = "i-fault003"
        cpu_name = _cpu_alarm(iid, ok_threshold)
        mem_name = _mem_alarm(iid, ok_threshold)
        disk_name = _disk_alarm(iid, "/data", new_disk_threshold)

        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_Disk_data": str(new_disk_threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        mock_cw.describe_alarms.side_effect = [
            {"MetricAlarms": [{"AlarmName": cpu_name, "Threshold": float(ok_threshold)}]},
            {"MetricAlarms": [{"AlarmName": mem_name, "Threshold": float(ok_threshold)}]},
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_name,
                        "Threshold": float(new_disk_threshold),
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/data"},
                            {"Name": "device", "Value": "xvdb1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    }
                ]
            },
            # _recreate_alarm_by_name(disk_name) 내부 describe_alarms 호출
            {
                "MetricAlarms": [
                    {
                        "AlarmName": disk_name,
                        "MetricName": "disk_used_percent",
                        "Threshold": float(new_disk_threshold),
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": iid},
                            {"Name": "path", "Value": "/data"},
                            {"Name": "device", "Value": "xvdb1"},
                            {"Name": "fstype", "Value": "ext4"},
                        ],
                    }
                ]
            },
        ]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager._delete_all_alarms_for_resource") as mock_delete_all, \
             patch.dict(os.environ, _ENV):
            sync_alarms_for_resource(iid, "EC2", tags)

        mock_delete_all.assert_not_called()
        assert not mock_delete_all.called, (
            "_delete_all_alarms_for_resource가 호출됨. "
            "부분 업데이트 시 전체 삭제 함수는 호출되지 않아야 함."
        )
