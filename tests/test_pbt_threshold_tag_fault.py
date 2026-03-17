"""
Bug Condition Exploration Test - Threshold_* 태그 변경 시 알람 재동기화 누락

Property 1 (Fault Condition): _handle_tag_change가 Threshold_* 태그만 변경된 경우
monitoring_involved = False로 즉시 return하여 sync_alarms_for_resource를 호출하지 않는 버그.

**Validates: Requirements 1.1, 1.2, 1.3**

EXPECTED: 수정 전 코드에서 이 테스트들은 FAIL함.
버그: monitoring_involved = False이면 Threshold_* 태그 변경도 무시하고 return.
"""

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from remediation_handler.lambda_handler import ParsedEvent, _handle_tag_change

# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

threshold_tag_keys = st.sampled_from([
    "Threshold_CPU",
    "Threshold_Memory",
    "Threshold_Disk_root",
    "Threshold_Disk_data",
    "Threshold_Connections",
])

threshold_values = st.integers(min_value=1, max_value=99).map(str)

resource_types_ec2 = st.just("EC2")
resource_types_rds = st.just("RDS")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_ec2_create_tags_parsed(instance_id: str, tag_key: str, tag_value: str) -> ParsedEvent:
    """EC2 CreateTags 이벤트로 Threshold_* 태그 추가하는 ParsedEvent 생성."""
    return ParsedEvent(
        resource_id=instance_id,
        resource_type="EC2",
        event_name="CreateTags",
        event_category="TAG_CHANGE",
        change_summary=f"CreateTags on EC2 {instance_id}",
        request_params={
            "tagSet": {
                "items": [{"key": tag_key, "value": tag_value}]
            }
        },
    )


def _make_rds_add_tags_parsed(db_id: str, tag_key: str, tag_value: str) -> ParsedEvent:
    """RDS AddTagsToResource 이벤트로 Threshold_* 태그 추가하는 ParsedEvent 생성."""
    return ParsedEvent(
        resource_id=db_id,
        resource_type="RDS",
        event_name="AddTagsToResource",
        event_category="TAG_CHANGE",
        change_summary=f"AddTagsToResource on RDS {db_id}",
        request_params={
            "tags": [{"key": tag_key, "value": tag_value}]
        },
    )


# ──────────────────────────────────────────────
# Property 1: Fault Condition
# Validates: Requirements 1.1, 1.2, 1.3
# ──────────────────────────────────────────────

class TestThresholdTagFaultCondition:
    """
    Threshold_* 태그만 변경될 때 sync_alarms_for_resource가 호출되어야 하는데
    수정 전 코드에서는 monitoring_involved=False로 즉시 return하여 호출되지 않는 버그.

    BUG: if not monitoring_involved: return  ← Threshold_* 태그도 무시됨
    """

    @given(tag_key=threshold_tag_keys, tag_value=threshold_values)
    @settings(max_examples=30)
    def test_threshold_tag_change_on_monitored_ec2_calls_sync(self, tag_key, tag_value):
        """
        **Validates: Requirements 1.1, 2.1, 2.2**

        Monitoring=on EC2에 Threshold_* 태그가 추가될 때
        sync_alarms_for_resource가 호출되어야 한다.
        수정 전 코드에서 FAIL (버그 존재 증명).
        """
        instance_id = "i-fault001"
        parsed = _make_ec2_create_tags_parsed(instance_id, tag_key, tag_value)
        current_tags = {"Monitoring": "on", "Name": "test-server", tag_key: tag_value}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_sync.assert_called_once_with(instance_id, "EC2", current_tags)

    @given(tag_key=threshold_tag_keys, tag_value=threshold_values)
    @settings(max_examples=20)
    def test_threshold_tag_change_on_monitored_rds_calls_sync(self, tag_key, tag_value):
        """
        **Validates: Requirements 1.1, 2.1**

        Monitoring=on RDS에 Threshold_* 태그가 추가될 때
        sync_alarms_for_resource가 호출되어야 한다.
        """
        db_id = "mydb-fault"
        parsed = _make_rds_add_tags_parsed(db_id, tag_key, tag_value)
        current_tags = {"Monitoring": "on", "Name": "mydb", tag_key: tag_value}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_sync.assert_called_once_with(db_id, "RDS", current_tags)

    def test_threshold_tag_change_without_monitoring_on_does_not_call_sync(self):
        """
        **Validates: Requirements 2.3**

        Monitoring=on 없는 리소스에 Threshold_* 태그가 추가될 때
        sync_alarms_for_resource가 호출되지 않아야 한다 (수정 전/후 모두 정상).
        """
        instance_id = "i-nomonitor"
        parsed = _make_ec2_create_tags_parsed(instance_id, "Threshold_CPU", "90")
        current_tags = {"Name": "test-server", "Threshold_CPU": "90"}  # Monitoring=on 없음

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_sync.assert_not_called()
