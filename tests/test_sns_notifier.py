"""
SNS_Notifier 테스트 - Property 7, 11 속성 테스트 + 단위 테스트

Requirements: 3.1, 3.2, 3.4, 5.2
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock, call

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.sns_notifier import (
    send_alert,
    send_remediation_alert,
    send_lifecycle_alert,
    send_error_alert,
)

TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:test-topic"
RESOURCE_TYPES = ["EC2", "RDS", "ELB"]
METRIC_NAMES = ["CPU", "Memory", "Connections", "Disk_root", "FreeMemoryGB", "RequestCount"]


def _capture_published_message(mock_sns: MagicMock) -> dict:
    """mock SNS client에서 publish된 메시지 JSON 파싱"""
    assert mock_sns.publish.called, "SNS publish가 호출되지 않음"
    kwargs = mock_sns.publish.call_args
    body = kwargs[1].get("Message") or kwargs[0][0] if kwargs[0] else kwargs[1]["Message"]
    return json.loads(body)


@pytest.fixture
def mock_sns(monkeypatch):
    """SNS 클라이언트 모킹 + SNS_TOPIC_ARN 환경변수 설정"""
    monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)
    mock_client = MagicMock()
    mock_client.publish.return_value = {"MessageId": "test-id"}
    with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
        yield mock_client


# ──────────────────────────────────────────────
# Property 7: 임계치 초과 알림 메시지 완전성
# Validates: Requirements 3.1, 3.2
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    resource_id=st.text(min_size=1, max_size=50).filter(lambda s: "\x00" not in s),
    resource_type=st.sampled_from(RESOURCE_TYPES),
    metric_name=st.sampled_from(METRIC_NAMES),
    current_value=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    threshold=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_property_7_alert_message_completeness(
    resource_id, resource_type, metric_name, current_value, threshold
):
    """Feature: aws-monitoring-engine, Property 7: 임계치 초과 알림 메시지 완전성"""
    published_body = None

    def fake_publish(**kwargs):
        nonlocal published_body
        published_body = kwargs["Message"]
        return {"MessageId": "test"}

    mock_client = MagicMock()
    mock_client.publish.side_effect = fake_publish

    with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
         patch.dict(os.environ, {"SNS_TOPIC_ARN": TOPIC_ARN}):
        send_alert(resource_id, resource_type, metric_name, current_value, threshold)

    assert published_body is not None, "SNS publish가 호출되지 않음"

    # JSON 파싱 가능 여부 검증
    try:
        msg = json.loads(published_body)
    except json.JSONDecodeError as e:
        pytest.fail(f"유효한 JSON이 아님: {e}")

    # 필수 필드 존재 여부 검증
    required_fields = {"resource_id", "resource_type", "metric_name", "current_value", "threshold"}
    missing = required_fields - set(msg.keys())
    assert not missing, f"필수 필드 누락: {missing}"

    # 값 일치 검증
    assert msg["resource_id"] == resource_id
    assert msg["resource_type"] == resource_type
    assert msg["metric_name"] == metric_name


# ──────────────────────────────────────────────
# Property 11: Remediation 완료 알림 메시지 완전성
# Validates: Requirements 5.2
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    resource_id=st.text(min_size=1, max_size=50).filter(lambda s: "\x00" not in s),
    resource_type=st.sampled_from(RESOURCE_TYPES),
    change_summary=st.text(min_size=1, max_size=200).filter(lambda s: "\x00" not in s),
    action_taken=st.sampled_from(["STOPPED", "DELETED"]),
)
def test_property_11_remediation_alert_completeness(
    resource_id, resource_type, change_summary, action_taken
):
    """Feature: aws-monitoring-engine, Property 11: Remediation 완료 알림 메시지 완전성"""
    published_body = None

    def fake_publish(**kwargs):
        nonlocal published_body
        published_body = kwargs["Message"]
        return {"MessageId": "test"}

    mock_client = MagicMock()
    mock_client.publish.side_effect = fake_publish

    with patch("common.sns_notifier._get_sns_client", return_value=mock_client), \
         patch.dict(os.environ, {"SNS_TOPIC_ARN": TOPIC_ARN}):
        send_remediation_alert(resource_id, resource_type, change_summary, action_taken)

    assert published_body is not None

    try:
        msg = json.loads(published_body)
    except json.JSONDecodeError as e:
        pytest.fail(f"유효한 JSON이 아님: {e}")

    required_fields = {"resource_id", "resource_type", "change_summary", "action_taken"}
    missing = required_fields - set(msg.keys())
    assert not missing, f"필수 필드 누락: {missing}"

    assert msg["resource_id"] == resource_id
    assert msg["resource_type"] == resource_type
    assert msg["change_summary"] == change_summary
    assert msg["action_taken"] == action_taken


# ──────────────────────────────────────────────
# 단위 테스트 - Requirements 3.1, 3.2, 3.4
# ──────────────────────────────────────────────

class TestSendAlert:
    def test_publishes_json_with_required_fields(self, mock_sns):
        send_alert("i-123", "EC2", "CPU", 95.0, 80.0)

        mock_sns.publish.assert_called_once()
        body = json.loads(mock_sns.publish.call_args[1]["Message"])

        assert body["alert_type"] == "THRESHOLD_EXCEEDED"
        assert body["resource_id"] == "i-123"
        assert body["resource_type"] == "EC2"
        assert body["metric_name"] == "CPU"
        assert body["current_value"] == 95.0
        assert body["threshold"] == 80.0
        assert "timestamp" in body

    def test_sns_failure_does_not_raise(self, monkeypatch):
        """SNS 발송 실패 시 예외가 전파되지 않음 - Requirements 3.4"""
        monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS connection error")

        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            # 예외가 발생하지 않아야 함
            send_alert("i-123", "EC2", "CPU", 95.0, 80.0)

    def test_no_topic_arn_does_not_raise(self, monkeypatch):
        """SNS_TOPIC_ARN 미설정 시 예외 없이 로그만 기록"""
        monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
        send_alert("i-123", "EC2", "CPU", 95.0, 80.0)  # 예외 없어야 함


class TestSendRemediationAlert:
    def test_publishes_json_with_required_fields(self, mock_sns):
        send_remediation_alert("i-123", "EC2", "InstanceType changed", "STOPPED")

        body = json.loads(mock_sns.publish.call_args[1]["Message"])
        assert body["alert_type"] == "REMEDIATION_PERFORMED"
        assert body["resource_id"] == "i-123"
        assert body["resource_type"] == "EC2"
        assert body["change_summary"] == "InstanceType changed"
        assert body["action_taken"] == "STOPPED"
        assert "timestamp" in body

    def test_sns_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("error")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_remediation_alert("i-123", "EC2", "change", "STOPPED")


class TestSendLifecycleAlert:
    def test_resource_deleted_alert(self, mock_sns):
        send_lifecycle_alert("i-123", "EC2", "RESOURCE_DELETED", "Monitoring=on 리소스가 삭제됨")

        body = json.loads(mock_sns.publish.call_args[1]["Message"])
        assert body["alert_type"] == "RESOURCE_DELETED"
        assert body["resource_id"] == "i-123"
        assert "Monitoring=on 리소스가 삭제됨" in body["message"]

    def test_monitoring_removed_alert(self, mock_sns):
        send_lifecycle_alert("i-123", "EC2", "MONITORING_REMOVED", "모니터링 대상에서 제외됨")

        body = json.loads(mock_sns.publish.call_args[1]["Message"])
        assert body["alert_type"] == "MONITORING_REMOVED"
        assert "모니터링 대상에서 제외됨" in body["message"]


class TestSendErrorAlert:
    def test_publishes_error_info(self, mock_sns):
        err = ValueError("something went wrong")
        send_error_alert("metric collection for i-123", err)

        body = json.loads(mock_sns.publish.call_args[1]["Message"])
        assert body["alert_type"] == "ERROR"
        assert "i-123" in body["context"]
        assert "something went wrong" in body["error"]
        assert body["error_type"] == "ValueError"

    def test_sns_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("error")
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_error_alert("context", Exception("err"))


# ──────────────────────────────────────────────
# 유형별 SNS 토픽 ARN 라우팅 테스트
# ──────────────────────────────────────────────

class TestTopicArnRouting:
    """알림 유형별 SNS 토픽 ARN 폴백 체인 테스트"""

    def test_alert_uses_specific_topic_when_set(self, monkeypatch):
        """SNS_TOPIC_ARN_ALERT 설정 시 해당 토픽으로 발송"""
        specific_arn = "arn:aws:sns:us-east-1:123:alert-topic"
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", specific_arn)
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:default-topic")

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_alert("i-123", "EC2", "CPU", 95.0, 80.0)

        assert mock_client.publish.call_args[1]["TopicArn"] == specific_arn

    def test_alert_falls_back_to_default_topic(self, monkeypatch):
        """SNS_TOPIC_ARN_ALERT 미설정 시 SNS_TOPIC_ARN으로 폴백"""
        default_arn = "arn:aws:sns:us-east-1:123:default-topic"
        monkeypatch.delenv("SNS_TOPIC_ARN_ALERT", raising=False)
        monkeypatch.setenv("SNS_TOPIC_ARN", default_arn)

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_alert("i-123", "EC2", "CPU", 95.0, 80.0)

        assert mock_client.publish.call_args[1]["TopicArn"] == default_arn

    def test_remediation_uses_specific_topic(self, monkeypatch):
        """SNS_TOPIC_ARN_REMEDIATION 설정 시 해당 토픽으로 발송"""
        specific_arn = "arn:aws:sns:us-east-1:123:remediation-topic"
        monkeypatch.setenv("SNS_TOPIC_ARN_REMEDIATION", specific_arn)
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:default-topic")

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_remediation_alert("i-123", "EC2", "change", "STOPPED")

        assert mock_client.publish.call_args[1]["TopicArn"] == specific_arn

    def test_lifecycle_uses_specific_topic(self, monkeypatch):
        """SNS_TOPIC_ARN_LIFECYCLE 설정 시 해당 토픽으로 발송"""
        specific_arn = "arn:aws:sns:us-east-1:123:lifecycle-topic"
        monkeypatch.setenv("SNS_TOPIC_ARN_LIFECYCLE", specific_arn)
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:default-topic")

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_lifecycle_alert("i-123", "EC2", "RESOURCE_DELETED", "삭제됨")

        assert mock_client.publish.call_args[1]["TopicArn"] == specific_arn

    def test_error_uses_specific_topic(self, monkeypatch):
        """SNS_TOPIC_ARN_ERROR 설정 시 해당 토픽으로 발송"""
        specific_arn = "arn:aws:sns:us-east-1:123:error-topic"
        monkeypatch.setenv("SNS_TOPIC_ARN_ERROR", specific_arn)
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:default-topic")

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_error_alert("context", Exception("err"))

        assert mock_client.publish.call_args[1]["TopicArn"] == specific_arn

    def test_all_types_fall_back_to_single_default(self, monkeypatch):
        """유형별 환경변수 없을 때 모두 SNS_TOPIC_ARN으로 폴백"""
        default_arn = "arn:aws:sns:us-east-1:123:default-topic"
        for env in ["SNS_TOPIC_ARN_ALERT", "SNS_TOPIC_ARN_REMEDIATION",
                    "SNS_TOPIC_ARN_LIFECYCLE", "SNS_TOPIC_ARN_ERROR"]:
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setenv("SNS_TOPIC_ARN", default_arn)

        mock_client = MagicMock()
        with patch("common.sns_notifier._get_sns_client", return_value=mock_client):
            send_alert("i-1", "EC2", "CPU", 95.0, 80.0)
            send_remediation_alert("i-1", "EC2", "change", "STOPPED")
            send_lifecycle_alert("i-1", "EC2", "RESOURCE_DELETED", "삭제됨")
            send_error_alert("ctx", Exception("err"))

        for c in mock_client.publish.call_args_list:
            assert c[1]["TopicArn"] == default_arn
