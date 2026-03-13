"""
Preservation Property Tests - 기존 JSON 필드 및 send_error_alert 형식 유지

Property 3: Preservation - 기존 JSON 필드 유지
Property 4: Preservation - send_error_alert 형식 유지

**Validates: Requirements 3.1, 3.2, 3.4, 3.5**

EXPECTED: These tests PASS on unfixed code to establish baseline behavior.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common.sns_notifier import (
    send_alert,
    send_error_alert,
    send_lifecycle_alert,
    send_remediation_alert,
)

# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

resource_id_st = st.text(min_size=1, max_size=80).filter(lambda s: s.strip())
resource_type_st = st.sampled_from(["EC2", "RDS", "ELB"])
metric_name_st = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())
positive_float_st = st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False)
text_st = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())
event_type_st = st.sampled_from(["RESOURCE_DELETED", "MONITORING_REMOVED"])


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_mock_sns():
    """Create a mock SNS client that captures published messages."""
    mock_client = MagicMock()
    mock_client.publish.return_value = {"MessageId": "test-id"}
    return mock_client


def _extract_message(mock_client) -> dict:
    """Extract the published message dict from the mock SNS client."""
    assert mock_client.publish.called, "SNS publish was not called"
    call_kwargs = mock_client.publish.call_args
    body = call_kwargs[1]["Message"] if "Message" in (call_kwargs[1] or {}) else call_kwargs[0][1]
    return json.loads(body)


_ENV_PATCH = {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}


# ──────────────────────────────────────────────
# Property Test 1: JSON field preservation for send_alert
# **Validates: Requirements 3.1**
# ──────────────────────────────────────────────

class TestSendAlertFieldPreservation:
    """send_alert must produce a message dict with all expected keys and correct values."""

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        metric_name=metric_name_st,
        current_value=positive_float_st,
        threshold=positive_float_st,
    )
    @settings(max_examples=50)
    def test_send_alert_json_fields(self, resource_id, resource_type, metric_name, current_value, threshold):
        """**Validates: Requirements 3.1**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            send_alert(resource_id, resource_type, metric_name, current_value, threshold)

        msg = _extract_message(mock_client)

        # All expected keys must be present
        expected_keys = {"alert_type", "resource_id", "resource_type", "metric_name",
                         "current_value", "threshold", "timestamp", "message"}
        assert expected_keys.issubset(msg.keys()), f"Missing keys: {expected_keys - msg.keys()}"

        # Value assertions
        assert msg["alert_type"] == "THRESHOLD_EXCEEDED"
        assert msg["resource_id"] == resource_id
        assert msg["resource_type"] == resource_type
        assert msg["metric_name"] == metric_name
        assert msg["current_value"] == current_value
        assert msg["threshold"] == threshold


# ──────────────────────────────────────────────
# Property Test 2: JSON field preservation for send_remediation_alert
# **Validates: Requirements 3.1**
# ──────────────────────────────────────────────

class TestSendRemediationAlertFieldPreservation:
    """send_remediation_alert must produce a message dict with all expected keys and correct values."""

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        change_summary=text_st,
        action_taken=text_st,
    )
    @settings(max_examples=50)
    def test_send_remediation_alert_json_fields(self, resource_id, resource_type, change_summary, action_taken):
        """**Validates: Requirements 3.1**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            send_remediation_alert(resource_id, resource_type, change_summary, action_taken)

        msg = _extract_message(mock_client)

        expected_keys = {"alert_type", "resource_id", "resource_type", "change_summary",
                         "action_taken", "timestamp", "message"}
        assert expected_keys.issubset(msg.keys()), f"Missing keys: {expected_keys - msg.keys()}"

        assert msg["alert_type"] == "REMEDIATION_PERFORMED"
        assert msg["resource_id"] == resource_id
        assert msg["resource_type"] == resource_type


# ──────────────────────────────────────────────
# Property Test 3: JSON field preservation for send_lifecycle_alert
# **Validates: Requirements 3.1**
# ──────────────────────────────────────────────

class TestSendLifecycleAlertFieldPreservation:
    """send_lifecycle_alert must produce a message dict with all expected keys."""

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        event_type=event_type_st,
        message_text=text_st,
    )
    @settings(max_examples=50)
    def test_send_lifecycle_alert_json_fields(self, resource_id, resource_type, event_type, message_text):
        """**Validates: Requirements 3.1**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            send_lifecycle_alert(resource_id, resource_type, event_type, message_text)

        msg = _extract_message(mock_client)

        expected_keys = {"alert_type", "resource_id", "resource_type", "message", "timestamp"}
        assert expected_keys.issubset(msg.keys()), f"Missing keys: {expected_keys - msg.keys()}"

        assert msg["resource_id"] == resource_id
        assert msg["resource_type"] == resource_type


# ──────────────────────────────────────────────
# Property Test 4: send_error_alert format preservation
# **Validates: Requirements 3.4**
# ──────────────────────────────────────────────

class TestSendErrorAlertFormatPreservation:
    """send_error_alert must preserve its message format and NOT contain (TagName:."""

    @given(
        context=text_st,
        error_msg=text_st,
    )
    @settings(max_examples=50)
    def test_send_error_alert_format(self, context, error_msg):
        """**Validates: Requirements 3.4**"""
        mock_client = _make_mock_sns()
        error = Exception(error_msg)
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            send_error_alert(context, error)

        msg = _extract_message(mock_client)

        expected_keys = {"alert_type", "context", "error", "error_type", "timestamp", "message"}
        assert expected_keys.issubset(msg.keys()), f"Missing keys: {expected_keys - msg.keys()}"

        assert msg["alert_type"] == "ERROR"
        assert msg["message"] == f"Operational error in {context}: {error_msg}"
        assert "(TagName:" not in msg["message"]


# ──────────────────────────────────────────────
# Property Test 5: SNS failure handling preservation
# **Validates: Requirements 3.2**
# ──────────────────────────────────────────────

class TestSNSFailureHandlingPreservation:
    """When SNS publish raises an exception, no exception propagates to caller."""

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        metric_name=metric_name_st,
        current_value=positive_float_st,
        threshold=positive_float_st,
    )
    @settings(max_examples=50)
    def test_send_alert_swallows_sns_exception(self, resource_id, resource_type, metric_name, current_value, threshold):
        """**Validates: Requirements 3.2**"""
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS publish failed")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            # Must not raise
            send_alert(resource_id, resource_type, metric_name, current_value, threshold)

    @given(
        context=text_st,
        error_msg=text_st,
    )
    @settings(max_examples=30)
    def test_send_error_alert_swallows_sns_exception(self, context, error_msg):
        """**Validates: Requirements 3.2**"""
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS publish failed")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            # Must not raise
            send_error_alert(context, Exception(error_msg))

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        change_summary=text_st,
        action_taken=text_st,
    )
    @settings(max_examples=30)
    def test_send_remediation_alert_swallows_sns_exception(self, resource_id, resource_type, change_summary, action_taken):
        """**Validates: Requirements 3.2**"""
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS publish failed")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            # Must not raise
            send_remediation_alert(resource_id, resource_type, change_summary, action_taken)

    @given(
        resource_id=resource_id_st,
        resource_type=resource_type_st,
        event_type=event_type_st,
        message_text=text_st,
    )
    @settings(max_examples=30)
    def test_send_lifecycle_alert_swallows_sns_exception(self, resource_id, resource_type, event_type, message_text):
        """**Validates: Requirements 3.2**"""
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS publish failed")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, _ENV_PATCH):
            # Must not raise
            send_lifecycle_alert(resource_id, resource_type, event_type, message_text)
