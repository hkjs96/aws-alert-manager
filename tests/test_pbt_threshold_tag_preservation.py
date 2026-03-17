"""
Preservation Property Tests - 기존 Monitoring 태그 처리 동작 보존

Property 2 (Preservation): _handle_tag_change에서 Threshold_* 태그가 없는 경우
(Monitoring 태그 추가/삭제, 일반 태그 변경) 기존 동작이 그대로 유지되어야 한다.

**Validates: Requirements 3.1, 3.2, 3.3**

EXPECTED: 수정 전/후 코드 모두에서 PASS해야 함 (기준 동작 확인 및 회귀 방지).
"""

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from remediation_handler.lambda_handler import ParsedEvent, _handle_tag_change

# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

non_monitoring_tag_keys = st.sampled_from(["Name", "Env", "Owner", "Project", "CostCenter"])
non_monitoring_values = st.text(min_size=1, max_size=20, alphabet=st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
))
instance_ids = st.just("i-preserve01")

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_parsed(resource_id, resource_type, event_name, tag_items) -> ParsedEvent:
    if resource_type == "EC2":
        params = {"tagSet": {"items": tag_items}}
    else:
        params = {"tags": tag_items}
    return ParsedEvent(
        resource_id=resource_id,
        resource_type=resource_type,
        event_name=event_name,
        event_category="TAG_CHANGE",
        change_summary=f"{event_name} on {resource_type} {resource_id}",
        request_params=params,
    )


# ──────────────────────────────────────────────
# Property 2: Preservation
# Validates: Requirements 3.1, 3.2, 3.3
# ──────────────────────────────────────────────

class TestMonitoringOnAddedPreservation:
    """
    Monitoring=on 태그 추가 시 create_alarms_for_resource 호출 동작 보존.
    Validates: Requirements 3.1
    """

    @given(instance_id=instance_ids)
    @settings(max_examples=20)
    def test_monitoring_on_added_calls_create_alarms(self, instance_id):
        """
        **Validates: Requirements 3.1**

        Monitoring=on CreateTags 이벤트 → create_alarms_for_resource 호출.
        수정 전/후 동일하게 동작해야 한다.
        """
        parsed = _make_parsed(
            instance_id, "EC2", "CreateTags",
            [{"key": "Monitoring", "value": "on"}]
        )
        current_tags = {"Monitoring": "on", "Name": "test-server"}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.create_alarms_for_resource",
                   return_value=["alarm1"]) as mock_create, \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_create.assert_called_once_with(instance_id, "EC2", current_tags)
        mock_sync.assert_not_called()


class TestMonitoringRemovedPreservation:
    """
    Monitoring 태그 삭제 시 알람 삭제 + lifecycle SNS 알림 동작 보존.
    Validates: Requirements 3.2
    """

    @given(instance_id=instance_ids)
    @settings(max_examples=20)
    def test_monitoring_tag_deleted_calls_delete_alarms(self, instance_id):
        """
        **Validates: Requirements 3.2**

        Monitoring DeleteTags 이벤트 → delete_alarms_for_resource + send_lifecycle_alert 호출.
        수정 전/후 동일하게 동작해야 한다.
        """
        parsed = _make_parsed(
            instance_id, "EC2", "DeleteTags",
            [{"key": "Monitoring", "value": ""}]
        )
        current_tags = {"Name": "test-server"}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.delete_alarms_for_resource") as mock_delete, \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_lifecycle, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_delete.assert_called_once_with(instance_id, "EC2")
        mock_lifecycle.assert_called_once()
        mock_sync.assert_not_called()

    @given(instance_id=instance_ids)
    @settings(max_examples=20)
    def test_monitoring_set_to_off_calls_delete_alarms(self, instance_id):
        """
        **Validates: Requirements 3.2**

        Monitoring=off CreateTags 이벤트 → delete_alarms_for_resource + send_lifecycle_alert 호출.
        """
        parsed = _make_parsed(
            instance_id, "EC2", "CreateTags",
            [{"key": "Monitoring", "value": "off"}]
        )
        current_tags = {"Name": "test-server", "Monitoring": "off"}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=current_tags), \
             patch("common.alarm_manager.delete_alarms_for_resource") as mock_delete, \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_lifecycle, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_delete.assert_called_once_with(instance_id, "EC2")
        mock_lifecycle.assert_called_once()
        mock_sync.assert_not_called()


class TestNonMonitoringTagIgnoredPreservation:
    """
    Monitoring/Threshold_* 무관한 일반 태그 변경 시 무시 동작 보존.
    Validates: Requirements 3.3
    """

    @given(tag_key=non_monitoring_tag_keys, tag_value=non_monitoring_values)
    @settings(max_examples=30)
    def test_non_monitoring_tag_change_is_ignored(self, tag_key, tag_value):
        """
        **Validates: Requirements 3.3**

        Name, Env 등 일반 태그 변경 → 아무것도 호출되지 않음.
        수정 전/후 동일하게 동작해야 한다.
        """
        instance_id = "i-preserve02"
        parsed = _make_parsed(
            instance_id, "EC2", "CreateTags",
            [{"key": tag_key, "value": tag_value}]
        )

        with patch("remediation_handler.lambda_handler.get_resource_tags") as mock_get_tags, \
             patch("common.alarm_manager.create_alarms_for_resource") as mock_create, \
             patch("common.alarm_manager.sync_alarms_for_resource") as mock_sync, \
             patch("common.alarm_manager.delete_alarms_for_resource") as mock_delete, \
             patch("remediation_handler.lambda_handler.send_error_alert"):

            _handle_tag_change(parsed)

        mock_create.assert_not_called()
        mock_sync.assert_not_called()
        mock_delete.assert_not_called()
        # 일반 태그 변경 시 get_resource_tags도 호출되지 않아야 함
        mock_get_tags.assert_not_called()
