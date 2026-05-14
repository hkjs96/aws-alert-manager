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
non_default_thresholds = st.integers(min_value=1, max_value=99).filter(
    lambda x: x != 80
)

# 변경되지 않는 알람 임계치 (기본값 80 유지)
OK_THRESHOLD = 80


def _cpu_alarm(iid: str, threshold: int) -> str:
    return f"[EC2] test-server CPUUtilization >{threshold}% ({iid})"


def _mem_alarm(iid: str, threshold: int) -> str:
    return (
        f"[EC2] test-server mem_used_percent >{threshold}% ({iid})"
    )


def _disk_alarm(iid: str, path: str, threshold: int) -> str:
    return (
        f"[EC2] test-server disk_used_percent({path})"
        f" >{threshold}% ({iid})"
    )


def _batch_response(alarms: list[dict]) -> dict:
    """Build a single describe_alarms batch response."""
    return {"MetricAlarms": alarms}



class TestSelectiveAlarmFaultCondition:
    """
    needs_recreate=True 시 result["ok"] 알람이 삭제되지 않아야 함.

    BUG: sync calls create_alarms_for_resource → _delete_all_alarms_for_resource,
    which deletes ALL alarms including result["ok"] alarms.
    """

    @given(new_disk_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_ok_alarms_not_deleted_when_disk_threshold_changes(
        self, new_disk_threshold,
    ):
        """
        **Property 1: Fault Condition** - 변경된 알람만 개별 삭제·재생성

        Disk_data 임계치 변경 시 CPU/Memory/Disk_root 알람(result["ok"])은
        삭제되지 않아야 한다.

        **Validates: Requirements 1.1, 2.1, 2.3**
        """
        iid = "i-fault001"
        cpu_name = _cpu_alarm(iid, OK_THRESHOLD)
        mem_name = _mem_alarm(iid, OK_THRESHOLD)
        disk_root_name = _disk_alarm(iid, "/", OK_THRESHOLD)
        disk_data_name = _disk_alarm(iid, "/data", new_disk_threshold)

        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_Disk_root": str(OK_THRESHOLD),
            "Threshold_Disk_data": str(new_disk_threshold),
        }

        existing_alarms = [
            cpu_name, mem_name, disk_root_name, disk_data_name,
        ]
        mock_cw = MagicMock()

        # New implementation: _describe_alarms_batch calls
        # describe_alarms(AlarmNames=[...all...]) ONCE
        all_alarm_infos = [
            {
                "AlarmName": cpu_name,
                "MetricName": "CPUUtilization",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
            {
                "AlarmName": mem_name,
                "MetricName": "mem_used_percent",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
            {
                "AlarmName": disk_root_name,
                "MetricName": "disk_used_percent",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                    {"Name": "path", "Value": "/"},
                    {"Name": "device", "Value": "xvda1"},
                    {"Name": "fstype", "Value": "ext4"},
                ],
            },
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
            },
        ]

        # First call: batch describe for sync
        # Second call: _recreate_alarm_by_name for disk_data
        mock_cw.describe_alarms.side_effect = [
            _batch_response(all_alarm_infos),
            _batch_response([all_alarm_infos[3]]),
        ]

        deleted_alarms = []

        def _track_delete(**kwargs):
            deleted_alarms.extend(kwargs.get("AlarmNames", []))

        mock_cw.delete_alarms.side_effect = _track_delete

        with (
            patch(
                "common._clients._get_cw_client",
                return_value=mock_cw,
            ),
            patch(
                "common.alarm_manager._find_alarms_for_resource",
                return_value=existing_alarms,
            ),
            patch.dict(os.environ, _ENV),
        ):
            sync_alarms_for_resource(iid, "EC2", tags)

        # result["ok"] 알람은 삭제되지 않아야 함
        assert cpu_name not in deleted_alarms, (
            f"CPU 알람 '{cpu_name}'이 삭제됨. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert mem_name not in deleted_alarms, (
            f"Memory 알람 '{mem_name}'이 삭제됨. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert disk_root_name not in deleted_alarms, (
            f"Disk_root 알람 '{disk_root_name}'이 삭제됨. "
            f"삭제된 알람: {deleted_alarms}"
        )

    @given(new_cpu_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_ok_alarms_not_deleted_when_cpu_threshold_changes(
        self, new_cpu_threshold,
    ):
        """
        **Property 1: Fault Condition** - CPU 임계치 변경 시 Memory/Disk 보존

        **Validates: Requirements 1.1, 2.1, 2.3**
        """
        iid = "i-fault002"
        cpu_name = _cpu_alarm(iid, new_cpu_threshold)
        mem_name = _mem_alarm(iid, OK_THRESHOLD)
        disk_name = _disk_alarm(iid, "/", OK_THRESHOLD)

        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_CPU": str(new_cpu_threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        all_alarm_infos = [
            {
                "AlarmName": cpu_name,
                "MetricName": "CPUUtilization",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
            {
                "AlarmName": mem_name,
                "MetricName": "mem_used_percent",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
            {
                "AlarmName": disk_name,
                "MetricName": "disk_used_percent",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                    {"Name": "path", "Value": "/"},
                    {"Name": "device", "Value": "xvda1"},
                    {"Name": "fstype", "Value": "ext4"},
                ],
            },
        ]

        # Batch describe + _recreate_alarm_by_name for cpu
        mock_cw.describe_alarms.side_effect = [
            _batch_response(all_alarm_infos),
            _batch_response([all_alarm_infos[0]]),
        ]

        deleted_alarms = []

        def _track_delete(**kwargs):
            deleted_alarms.extend(kwargs.get("AlarmNames", []))

        mock_cw.delete_alarms.side_effect = _track_delete

        with (
            patch(
                "common._clients._get_cw_client",
                return_value=mock_cw,
            ),
            patch(
                "common.alarm_manager._find_alarms_for_resource",
                return_value=existing_alarms,
            ),
            patch.dict(os.environ, _ENV),
        ):
            sync_alarms_for_resource(iid, "EC2", tags)

        assert mem_name not in deleted_alarms, (
            f"Memory 알람 '{mem_name}'이 삭제됨. "
            f"삭제된 알람: {deleted_alarms}"
        )
        assert disk_name not in deleted_alarms, (
            f"Disk 알람 '{disk_name}'이 삭제됨. "
            f"삭제된 알람: {deleted_alarms}"
        )

    @given(new_disk_threshold=non_default_thresholds)
    @settings(max_examples=30)
    def test_delete_all_not_called_on_partial_update(
        self, new_disk_threshold,
    ):
        """
        **Property 1: Fault Condition** - _delete_all 미호출 확인

        **Validates: Requirements 1.2, 2.1**
        """
        iid = "i-fault003"
        cpu_name = _cpu_alarm(iid, OK_THRESHOLD)
        mem_name = _mem_alarm(iid, OK_THRESHOLD)
        disk_name = _disk_alarm(iid, "/data", new_disk_threshold)

        tags = {
            "Monitoring": "on",
            "Name": "test-server",
            "Threshold_Disk_data": str(new_disk_threshold),
        }

        existing_alarms = [cpu_name, mem_name, disk_name]
        mock_cw = MagicMock()

        all_alarm_infos = [
            {
                "AlarmName": cpu_name,
                "MetricName": "CPUUtilization",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
            {
                "AlarmName": mem_name,
                "MetricName": "mem_used_percent",
                "Threshold": float(OK_THRESHOLD),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": iid},
                ],
            },
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
            },
        ]

        mock_cw.describe_alarms.side_effect = [
            _batch_response(all_alarm_infos),
            _batch_response([all_alarm_infos[2]]),
        ]

        with (
            patch(
                "common._clients._get_cw_client",
                return_value=mock_cw,
            ),
            patch(
                "common.alarm_manager._find_alarms_for_resource",
                return_value=existing_alarms,
            ),
            patch(
                "common.alarm_manager._delete_all_alarms_for_resource",
            ) as mock_delete_all,
            patch.dict(os.environ, _ENV),
        ):
            sync_alarms_for_resource(iid, "EC2", tags)

        mock_delete_all.assert_not_called()
