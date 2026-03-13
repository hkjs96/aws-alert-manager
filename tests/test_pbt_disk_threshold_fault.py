"""
Bug Condition Exploration Test - 디스크 알람 경로별 임계치 조회 누락

Property 1 (Fault Condition): sync_alarms_for_resource가 디스크 알람의 임계치를
비교할 때 경로별 태그 키(Disk_root, Disk_data 등)를 사용해야 하는데,
일괄적으로 get_threshold(resource_tags, "Disk")를 호출하여 항상 기본값(80)만 사용하는 버그.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**

EXPECTED: These tests FAIL on unfixed code because sync uses
get_threshold(tags, "Disk") → 80 (default) instead of path-specific value,
so it sees threshold != 80 and marks as "updated" instead of "ok".
"""

import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import sync_alarms_for_resource
from common.tag_resolver import disk_path_to_tag_suffix


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

# Disk paths that map to known tag suffixes
disk_paths = st.sampled_from(["/", "/data", "/var/log"])

# Threshold values that differ from default (80) to trigger the bug
non_default_thresholds = st.integers(min_value=1, max_value=99).filter(lambda x: x != 80)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_alarm_name(instance_id: str, path: str, threshold: float) -> str:
    """Generate a realistic disk alarm name containing disk_used_percent."""
    suffix = disk_path_to_tag_suffix(path)
    path_display = f"disk_used_percent({path})"
    return f"[EC2] test-server {path_display} >{int(threshold)}% ({instance_id})"


def _make_describe_alarms_response(instance_id, path, threshold):
    """Build a describe_alarms response with a single disk alarm."""
    return {
        "MetricAlarms": [
            {
                "AlarmName": _make_alarm_name(instance_id, path, threshold),
                "Threshold": float(threshold),
                "Dimensions": [
                    {"Name": "InstanceId", "Value": instance_id},
                    {"Name": "path", "Value": path},
                    {"Name": "device", "Value": "xvda1"},
                    {"Name": "fstype", "Value": "ext4"},
                ],
            }
        ]
    }


# ──────────────────────────────────────────────
# Property 1: Fault Condition - path-specific threshold lookup
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4
# ──────────────────────────────────────────────

class TestDiskThresholdSync:
    """
    When a disk alarm exists with threshold matching the path-specific tag,
    sync should classify it as "ok" (not "updated").

    BUG: sync calls get_threshold(tags, "Disk") → 80 (default) instead of
    get_threshold(tags, "Disk_root") → tag value, causing mismatch.
    """

    @given(path=disk_paths, threshold=non_default_thresholds)
    @settings(max_examples=50)
    def test_disk_alarm_with_matching_path_threshold_is_ok(self, path, threshold):
        """
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

        For any disk path and path-specific threshold tag, when the existing
        alarm threshold matches the tag value, sync should report "ok".
        """
        instance_id = "i-test123"
        suffix = disk_path_to_tag_suffix(path)
        alarm_name = _make_alarm_name(instance_id, path, threshold)

        # Resource tags with path-specific threshold (e.g., Threshold_Disk_root=55)
        resource_tags = {
            "Monitoring": "on",
            "Name": "test-server",
            f"Threshold_Disk_{suffix}": str(threshold),
        }

        # Mock CW client
        mock_cw = MagicMock()
        mock_cw.describe_alarms.return_value = _make_describe_alarms_response(
            instance_id, path, threshold
        )

        # Existing alarms include the disk alarm
        existing_alarms = [alarm_name]

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing_alarms), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]) as mock_create, \
             patch.dict(os.environ, {"ENVIRONMENT": "prod", "SNS_TOPIC_ARN_ALERT": ""}):

            result = sync_alarms_for_resource(instance_id, "EC2", resource_tags)

        # The alarm threshold matches the tag → should be "ok", not "updated"
        assert alarm_name in result["ok"], (
            f"Expected alarm '{alarm_name}' in result['ok'] but got: "
            f"ok={result['ok']}, updated={result['updated']}. "
            f"Bug: sync uses get_threshold(tags, 'Disk') → 80 instead of "
            f"get_threshold(tags, 'Disk_{suffix}') → {threshold}"
        )
        assert alarm_name not in result["updated"], (
            f"Alarm '{alarm_name}' should NOT be in result['updated'] "
            f"when threshold ({threshold}) matches tag Threshold_Disk_{suffix}={threshold}"
        )
