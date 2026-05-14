"""
Bug Condition Exploration Test - TagName 알림 메시지 표시 누락

Property 1 (Fault Condition): 알림 메시지에 TagName 포함 확인
- For any non-empty tag_name, message should contain (TagName: <tag_name>)
- For empty/None tag_name, message should contain (TagName: N/A)

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

EXPECTED: These tests FAIL on unfixed code because the alert functions
do not accept a tag_name parameter yet. Failure confirms the bug exists.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common.sns_notifier import (
    send_alert,
    send_lifecycle_alert,
    send_remediation_alert,
)

# Strategy: non-empty tag_name strings (printable, no whitespace-only)
non_empty_tag_name = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

# Strategy: empty-ish tag_name values (empty string or None)
empty_tag_name = st.sampled_from(["", None])


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


# ──────────────────────────────────────────────
# Property 1: Non-empty tag_name → message contains (TagName: <tag_name>)
# Validates: Requirements 2.1, 2.2, 2.3
# ──────────────────────────────────────────────

class TestSendAlertTagName:
    """send_alert should include (TagName: <tag_name>) in message."""

    @given(tag_name=non_empty_tag_name)
    @settings(max_examples=50)
    def test_send_alert_includes_tag_name(self, tag_name):
        """**Validates: Requirements 2.1**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_alert("i-abc123", "EC2", "CPU", 95.0, 80.0, tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert f"(TagName: {tag_name})" in msg["message"]

    @given(tag_name=non_empty_tag_name)
    @settings(max_examples=50)
    def test_send_remediation_alert_includes_tag_name(self, tag_name):
        """**Validates: Requirements 2.2**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_remediation_alert("i-abc123", "EC2", "type changed", "STOPPED", tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert f"(TagName: {tag_name})" in msg["message"]

    @given(tag_name=non_empty_tag_name)
    @settings(max_examples=50)
    def test_send_lifecycle_alert_includes_tag_name(self, tag_name):
        """**Validates: Requirements 2.3**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_lifecycle_alert("i-abc123", "EC2", "RESOURCE_DELETED", "deleted", tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert f"(TagName: {tag_name})" in msg["message"]


# ──────────────────────────────────────────────
# Property 2: Empty/None tag_name → message contains (TagName: N/A)
# Validates: Requirements 2.4
# ──────────────────────────────────────────────

class TestSendAlertTagNameFallback:
    """When tag_name is empty or None, message should contain (TagName: N/A)."""

    @given(tag_name=empty_tag_name)
    @settings(max_examples=10)
    def test_send_alert_fallback_na(self, tag_name):
        """**Validates: Requirements 2.4**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_alert("i-abc123", "EC2", "CPU", 95.0, 80.0, tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert "(TagName: N/A)" in msg["message"]

    @given(tag_name=empty_tag_name)
    @settings(max_examples=10)
    def test_send_remediation_alert_fallback_na(self, tag_name):
        """**Validates: Requirements 2.4**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_remediation_alert("i-abc123", "EC2", "type changed", "STOPPED", tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert "(TagName: N/A)" in msg["message"]

    @given(tag_name=empty_tag_name)
    @settings(max_examples=10)
    def test_send_lifecycle_alert_fallback_na(self, tag_name):
        """**Validates: Requirements 2.4**"""
        mock_client = _make_mock_sns()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
             patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test"}):
            send_lifecycle_alert("i-abc123", "EC2", "RESOURCE_DELETED", "deleted", tag_name=tag_name)
        msg = _extract_message(mock_client)
        assert "(TagName: N/A)" in msg["message"]
