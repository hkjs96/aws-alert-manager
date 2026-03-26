"""
Bug Condition Exploration Test - 디스크 알람 경로별 임계치 조회 누락

Property 1 (Fault Condition): sync_alarms_for_resource가 디스크 알람의 임계치를
비교할 때 경로별 태그 키(Disk_root, Disk_data 등)를 사용해야 하는데,
일괄적으로 get_threshold(resource_tags, "Disk")를 호출하여 항상 기본값(80)만
사용하는 버그.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**

EXPECTED: These tests FAIL on unfixed code because sync uses
get_threshold(tags, "Disk") -> 80 (default) instead of path-specific value.
"""

import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import sync_alarms_for_resource
from common.tag_resolver import disk_path_to_tag_suffix

# Disk paths that map to known tag suffixes
disk_paths = st.sampled_from(["/", "/data", "/var/log"])

# Threshold values that differ from default (80)
non_default_thresholds = st.integers(
    min_value=1, max_value=99,
).filter(lambda x: x != 80)

_ENV = {"ENVIRONMENT": "prod", "SNS_TOPIC_ARN_ALERT": ""}


def _make_alarm_name(iid: str, path: str, threshold: float) -> str:
    path_display = f"disk_used_percent({path})"
    return (
        f"[EC2] test-server {path_display}"
        f" >{int(threshold)}% ({iid})"
    )


def _batch_response(alarms: list[dict]) -> dict:
    return {"MetricAlarms": alarms}


class TestDiskThresholdSync:
    """
    When a disk alarm exists with threshold matching the path-specific tag,
    sync should classify it as "ok" (not "updated").

    BUG: sync calls get_threshold(tags, "Disk") -> 80 instead of
    get_threshold(tags, "Disk_root") -> tag value.
    """

    @given(path=disk_paths, threshold=non_default_thresholds)
    @settings(max_examples=50)
    def test_disk_alarm_with_matching_path_threshold_is_ok(
        self, path, threshold,
    ):
        """
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

        For any disk path and path-specific threshold tag, when the
        existing alarm threshold matches the tag value, sync reports "ok".
        """
        iid = "i-test123"
        suffix = disk_path_to_tag_suffix(path)
        alarm_name = _make_alarm_name(iid, path, threshold)

        resource_tags = {
            "Monitoring": "on",
            "Name": "test-server",
            f"Threshold_Disk_{suffix}": str(threshold),
        }

        existing_alarms = [alarm_name]
        mock_cw = MagicMock()

        # New impl: single batch describe_alarms with MetricName
        alarm_info = {
            "AlarmName": alarm_name,
            "MetricName": "disk_used_percent",
            "Threshold": float(threshold),
            "Dimensions": [
                {"Name": "InstanceId", "Value": iid},
                {"Name": "path", "Value": path},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "ext4"},
            ],
        }

        mock_cw.describe_alarms.return_value = _batch_response(
            [alarm_info],
        )

        with (
            patch(
                "common.alarm_manager._get_cw_client",
                return_value=mock_cw,
            ),
            patch(
                "common.alarm_manager._find_alarms_for_resource",
                return_value=existing_alarms,
            ),
            patch(
                "common.alarm_manager.create_alarms_for_resource",
                return_value=[],
            ),
            patch.dict(os.environ, _ENV),
        ):
            result = sync_alarms_for_resource(
                iid, "EC2", resource_tags,
            )

        assert alarm_name in result["ok"], (
            f"Expected alarm in ok but got: "
            f"ok={result['ok']}, updated={result['updated']}"
        )
        assert alarm_name not in result["updated"], (
            f"Alarm should NOT be in updated when threshold matches"
        )
