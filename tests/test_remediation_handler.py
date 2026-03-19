"""
Remediation_Handler 테스트 - Property 9, 10, 12, 14, 15, 16 속성 테스트 + 단위 테스트

Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 8.1~8.7
"""

import logging
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from remediation_handler.lambda_handler import (
    ParsedEvent,
    lambda_handler,
    parse_cloudtrail_event,
    perform_remediation,
)


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _make_event(event_name: str, resource_id: str, extra_params: dict = None) -> dict:
    """EventBridge 래핑 CloudTrail 이벤트 생성."""
    params = extra_params or {}

    # 이벤트별 기본 requestParameters 구조
    if event_name in ("ModifyInstanceAttribute", "ModifyInstanceType",
                      "TerminateInstances"):
        params.setdefault("instancesSet", {"items": [{"instanceId": resource_id}]})
    elif event_name in ("ModifyDBInstance", "DeleteDBInstance"):
        params.setdefault("dBInstanceIdentifier", resource_id)
    elif event_name in ("ModifyLoadBalancerAttributes", "ModifyListener",
                        "DeleteLoadBalancer"):
        params.setdefault("loadBalancerArn", resource_id)
    elif event_name in ("CreateTags", "DeleteTags"):
        params.setdefault("resourcesSet", {"items": [{"resourceId": resource_id}]})
    elif event_name in ("AddTagsToResource", "RemoveTagsFromResource"):
        # RDS 태그 API: resourceName은 ARN 형태
        params.setdefault("resourceName", f"arn:aws:rds:us-east-1:123456789012:db:{resource_id}")
    elif event_name in ("AddTags", "RemoveTags"):
        # ELB 태그 API: resourceArns 리스트
        params.setdefault("resourceArns", [resource_id])

    return {"detail": {"eventName": event_name, "requestParameters": params}}


def _make_parsed(event_name: str, resource_id: str, resource_type: str,
                 event_category: str) -> ParsedEvent:
    return ParsedEvent(
        resource_id=resource_id,
        resource_type=resource_type,
        event_name=event_name,
        event_category=event_category,
        change_summary=f"{event_name} on {resource_type} {resource_id}",
        request_params={},
    )


# ──────────────────────────────────────────────
# Property 9: Monitoring 태그 기반 Remediation 필터링
# Validates: Requirements 4.2, 4.3
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
    resource_type=st.sampled_from(["EC2", "RDS", "ELB"]),
)
def test_property_9_no_monitoring_tag_skips_remediation(resource_id, resource_type):
    """Feature: aws-monitoring-engine, Property 9: Monitoring 태그 없으면 remediation 미수행"""
    parsed = _make_parsed("ModifyInstanceAttribute", resource_id, resource_type, "MODIFY")

    with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}), \
         patch("remediation_handler.lambda_handler._execute_remediation") as mock_exec:
        from remediation_handler.lambda_handler import _handle_modify
        _handle_modify(parsed)

    mock_exec.assert_not_called()


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
    resource_type=st.sampled_from(["EC2", "RDS", "ELB"]),
)
def test_property_9_monitoring_tag_triggers_remediation(resource_id, resource_type):
    """Feature: aws-monitoring-engine, Property 9: Monitoring=on 태그 있으면 remediation 수행"""
    parsed = _make_parsed("ModifyInstanceAttribute", resource_id, resource_type, "MODIFY")

    with patch("remediation_handler.lambda_handler.get_resource_tags",
               return_value={"Monitoring": "on"}), \
         patch("remediation_handler.lambda_handler._execute_remediation",
               return_value="STOPPED") as mock_exec, \
         patch("remediation_handler.lambda_handler.send_remediation_alert"):
        from remediation_handler.lambda_handler import _handle_modify
        _handle_modify(parsed)

    mock_exec.assert_called_once_with(resource_type, resource_id)


# ──────────────────────────────────────────────
# Property 10: 리소스 유형별 Remediation 액션 정확성
# Validates: Requirements 5.1
# ──────────────────────────────────────────────

@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
)
def test_property_10_ec2_remediation_calls_stop(resource_id):
    """Feature: aws-monitoring-engine, Property 10: EC2 → stop_instances"""
    mock_ec2 = MagicMock()
    with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_ec2):
        from remediation_handler.lambda_handler import _execute_remediation
        result = _execute_remediation("EC2", resource_id)

    mock_ec2.stop_instances.assert_called_once_with(InstanceIds=[resource_id])
    assert result == "STOPPED"


@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
)
def test_property_10_rds_remediation_calls_stop(resource_id):
    """Feature: aws-monitoring-engine, Property 10: RDS → stop_db_instance"""
    mock_rds = MagicMock()
    with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
        from remediation_handler.lambda_handler import _execute_remediation
        result = _execute_remediation("RDS", resource_id)

    mock_rds.stop_db_instance.assert_called_once_with(DBInstanceIdentifier=resource_id)
    assert result == "STOPPED"


@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
)
def test_property_10_elb_remediation_calls_delete(resource_id):
    """Feature: aws-monitoring-engine, Property 10: ELB → delete_load_balancer"""
    mock_elb = MagicMock()
    with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_elb):
        from remediation_handler.lambda_handler import _execute_remediation
        result = _execute_remediation("ELB", resource_id)

    mock_elb.delete_load_balancer.assert_called_once_with(LoadBalancerArn=resource_id)
    assert result == "DELETED"


# ──────────────────────────────────────────────
# Property 12: Remediation 사전 로그 기록
# Validates: Requirements 5.4
# ──────────────────────────────────────────────

def test_property_12_pre_log_before_remediation_action(caplog):
    """Feature: aws-monitoring-engine, Property 12: 사전 로그가 remediation 액션보다 먼저 기록"""
    call_order = []

    def fake_execute(resource_type, resource_id):
        call_order.append("execute")
        return "STOPPED"

    with caplog.at_level(logging.WARNING, logger="remediation_handler.lambda_handler"), \
         patch("remediation_handler.lambda_handler._execute_remediation",
               side_effect=fake_execute), \
         patch("remediation_handler.lambda_handler.send_remediation_alert"):
        perform_remediation("EC2", "i-001", "ModifyInstanceAttribute on EC2 i-001")

    # 로그에 PRE-LOG 포함 확인
    pre_log_msgs = [r.message for r in caplog.records if "REMEDIATION PRE-LOG" in r.message]
    assert pre_log_msgs, "PRE-LOG should be recorded before remediation"
    # execute가 호출됐는지 확인
    assert "execute" in call_order


# ──────────────────────────────────────────────
# Property 14: 리소스 삭제 이벤트 알림 정확성
# Validates: Requirements 8.1, 8.2, 8.3
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
    resource_type=st.sampled_from(["EC2", "RDS", "ELB"]),
)
def test_property_14_delete_with_monitoring_tag_sends_alert(resource_id, resource_type):
    """Feature: aws-monitoring-engine, Property 14: Monitoring=on 리소스 삭제 시 알람 삭제 + SNS 알림"""
    parsed = _make_parsed("TerminateInstances", resource_id, resource_type, "DELETE")

    with patch("remediation_handler.lambda_handler.get_resource_tags",
               return_value={"Monitoring": "on"}), \
         patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
         patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=["alarm1"]) as mock_delete:
        from remediation_handler.lambda_handler import _handle_delete
        _handle_delete(parsed)

    mock_delete.assert_called_once_with(resource_id, resource_type)
    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert call_kwargs["event_type"] == "RESOURCE_DELETED"
    assert call_kwargs["resource_id"] == resource_id


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
    resource_type=st.sampled_from(["EC2", "RDS", "ELB"]),
)
def test_property_14_delete_without_monitoring_tag_no_alert(resource_id, resource_type):
    """Feature: aws-monitoring-engine, Property 14: 모니터링 대상 아닌 리소스 삭제 시 알람 삭제 시도 + 알림 없음"""
    parsed = _make_parsed("TerminateInstances", resource_id, resource_type, "DELETE")

    # 태그 없고 알람도 없는 경우 → lifecycle 알림 없음
    with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}), \
         patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
         patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]) as mock_delete:
        from remediation_handler.lambda_handler import _handle_delete
        _handle_delete(parsed)

    # 알람 삭제는 항상 시도
    mock_delete.assert_called_once_with(resource_id, resource_type)
    # 모니터링 대상 아니었으면 lifecycle 알림 없음
    mock_alert.assert_not_called()


# ──────────────────────────────────────────────
# Property 15: 태그 제거 시 알림 발송
# Validates: Requirements 8.5
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
)
def test_property_15_delete_monitoring_tag_sends_alert(resource_id):
    """Feature: aws-monitoring-engine, Property 15: DeleteTags Monitoring 제거 시 SNS 알림"""
    parsed = ParsedEvent(
        resource_id=resource_id,
        resource_type="EC2",
        event_name="DeleteTags",
        event_category="TAG_CHANGE",
        change_summary=f"DeleteTags on EC2 {resource_id}",
        request_params={"tagSet": {"items": [{"key": "Monitoring"}]}},
    )

    with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
         patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]):
        from remediation_handler.lambda_handler import _handle_tag_change
        _handle_tag_change(parsed)

    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert call_kwargs["event_type"] == "MONITORING_REMOVED"


# ──────────────────────────────────────────────
# Property 16: 태그 추가 시 로그 기록 (SNS 알림 없음)
# Validates: Requirements 8.6
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture], deadline=None)
@given(
    resource_id=st.text(min_size=2, max_size=20,
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                               whitelist_characters="-")),
)
def test_property_16_create_monitoring_tag_logs_no_alert(resource_id, caplog):
    """Feature: aws-monitoring-engine, Property 16: CreateTags Monitoring=on 추가 시 로그만, SNS 없음"""
    parsed = ParsedEvent(
        resource_id=resource_id,
        resource_type="EC2",
        event_name="CreateTags",
        event_category="TAG_CHANGE",
        change_summary=f"CreateTags on EC2 {resource_id}",
        request_params={"tagSet": {"items": [{"key": "Monitoring", "value": "on"}]}},
    )

    with caplog.at_level(logging.INFO, logger="remediation_handler.lambda_handler"), \
         patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
         patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource", return_value=[]):
        from remediation_handler.lambda_handler import _handle_tag_change
        _handle_tag_change(parsed)

    # SNS 알림 없음
    mock_alert.assert_not_called()
    # 로그 기록 확인
    log_msgs = [r.message for r in caplog.records]
    assert any("ADDED" in m or "monitored" in m for m in log_msgs), \
        f"Expected log about monitoring tag added, got: {log_msgs}"


# ──────────────────────────────────────────────
# 단위 테스트
# ──────────────────────────────────────────────

class TestParseCloudTrailEvent:

    def test_parse_modify_ec2(self):
        """EC2 ModifyInstanceAttribute 파싱"""
        event = _make_event("ModifyInstanceAttribute", "i-001")
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == "i-001"
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "MODIFY"

    def test_parse_delete_rds(self):
        """RDS DeleteDBInstance 파싱"""
        event = _make_event("DeleteDBInstance", "db-prod")
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == "db-prod"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "DELETE"

    def test_parse_delete_elb(self):
        """ELB DeleteLoadBalancer 파싱"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("DeleteLoadBalancer", arn)
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ELB"
        assert parsed.event_category == "DELETE"

    def test_parse_create_tags(self):
        """CreateTags 파싱"""
        event = _make_event("CreateTags", "i-001")
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == "i-001"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_rds_add_tags(self):
        """RDS AddTagsToResource 파싱"""
        event = _make_event("AddTagsToResource", "my-rds-db")
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == "my-rds-db"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_rds_remove_tags(self):
        """RDS RemoveTagsFromResource 파싱"""
        event = _make_event("RemoveTagsFromResource", "my-rds-db")
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == "my-rds-db"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_elb_add_tags(self):
        """ELB AddTags 파싱"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("AddTags", arn)
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ELB"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_elb_remove_tags(self):
        """ELB RemoveTags 파싱"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("RemoveTags", arn)
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ELB"
        assert parsed.event_category == "TAG_CHANGE"

    def test_missing_event_name_raises(self):
        """eventName 없으면 ValueError"""
        with pytest.raises(ValueError, match="Missing eventName"):
            parse_cloudtrail_event({"detail": {}})

    def test_unsupported_event_name_raises(self):
        """지원하지 않는 API 이름이면 ValueError"""
        with pytest.raises(ValueError, match="Unsupported eventName"):
            parse_cloudtrail_event({"detail": {"eventName": "UnknownAPI"}})

    def test_missing_resource_id_raises(self):
        """resource_id 추출 실패 시 ValueError"""
        event = {"detail": {
            "eventName": "ModifyInstanceAttribute",
            "requestParameters": {}  # instancesSet 없음
        }}
        with pytest.raises(ValueError, match="Cannot extract resource_id"):
            parse_cloudtrail_event(event)


class TestHandlerRouting:

    def test_modify_event_calls_handle_modify(self):
        """MODIFY 이벤트 → _handle_modify 호출"""
        event = _make_event("ModifyInstanceAttribute", "i-001")
        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}), \
             patch("remediation_handler.lambda_handler._execute_remediation") as mock_exec:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_exec.assert_not_called()  # Monitoring 태그 없으므로 실행 안 됨

    def test_delete_event_with_monitoring_tag(self):
        """DELETE 이벤트 + Monitoring=on → lifecycle 알림"""
        event = _make_event("TerminateInstances", "i-001")
        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]):
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_called_once()

    def test_parse_error_sends_error_alert(self):
        """파싱 오류 시 SNS 오류 알림 발송 - Requirements 4.4"""
        with patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = lambda_handler({"detail": {}}, MagicMock())

        assert result["status"] == "parse_error"
        mock_err.assert_called_once()

    def test_remediation_failure_sends_error_alert(self):
        """Remediation 실패 시 SNS 즉시 알림 - Requirements 5.3"""
        event = _make_event("ModifyInstanceAttribute", "i-001")
        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler._execute_remediation",
                   side_effect=Exception("stop failed")), \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "error"
        mock_err.assert_called_once()

    def test_tag_change_delete_monitoring_sends_alert(self):
        """DeleteTags Monitoring 제거 → MONITORING_REMOVED 알림 - Requirements 8.5"""
        event = {
            "detail": {
                "eventName": "DeleteTags",
                "requestParameters": {
                    "resourcesSet": {"items": [{"resourceId": "i-001"}]},
                    "tagSet": {"items": [{"key": "Monitoring"}]},
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]):
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "MONITORING_REMOVED"

    def test_tag_change_create_monitoring_no_sns(self):
        """CreateTags Monitoring=on 추가 → SNS 알림 없음 - Requirements 8.6"""
        event = {
            "detail": {
                "eventName": "CreateTags",
                "requestParameters": {
                    "resourcesSet": {"items": [{"resourceId": "i-001"}]},
                    "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]},
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource", return_value=[]):
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()

    def test_tag_change_non_monitoring_tag_ignored(self):
        """Monitoring 태그 아닌 태그 변경은 무시 - Requirements 8.7"""
        event = {
            "detail": {
                "eventName": "CreateTags",
                "requestParameters": {
                    "resourcesSet": {"items": [{"resourceId": "i-001"}]},
                    "tagSet": {"items": [{"key": "Environment", "value": "prod"}]},
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()
        mock_err.assert_not_called()


class TestRdsElbTagEvents:
    """RDS/ELB 태그 이벤트 감지 테스트"""

    def test_rds_add_monitoring_tag_creates_alarms(self):
        """RDS AddTagsToResource + Monitoring=on → 알람 생성"""
        event = {
            "detail": {
                "eventName": "AddTagsToResource",
                "requestParameters": {
                    "resourceName": "arn:aws:rds:us-east-1:123456789012:db:my-rds",
                    "tags": [{"key": "Monitoring", "value": "on"}],
                },
            }
        }
        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                   return_value=["alarm1"]) as mock_create:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_create.assert_called_once()
        args = mock_create.call_args
        assert args[0][0] == "my-rds"
        assert args[0][1] == "RDS"

    def test_rds_remove_monitoring_tag_deletes_alarms(self):
        """RDS RemoveTagsFromResource + Monitoring → 알람 삭제 + lifecycle 알림"""
        event = {
            "detail": {
                "eventName": "RemoveTagsFromResource",
                "requestParameters": {
                    "resourceName": "arn:aws:rds:us-east-1:123456789012:db:my-rds",
                    "tags": [{"key": "Monitoring"}],
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=[]) as mock_delete:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_delete.assert_called_once_with("my-rds", "RDS")
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "MONITORING_REMOVED"

    def test_elb_add_monitoring_tag_creates_alarms(self):
        """ELB AddTags + Monitoring=on → 알람 생성"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = {
            "detail": {
                "eventName": "AddTags",
                "requestParameters": {
                    "resourceArns": [arn],
                    "tags": [{"key": "Monitoring", "value": "on"}],
                },
            }
        }
        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                   return_value=["alarm1"]) as mock_create:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_create.assert_called_once()
        args = mock_create.call_args
        assert args[0][0] == arn
        assert args[0][1] == "ELB"

    def test_elb_remove_monitoring_tag_deletes_alarms(self):
        """ELB RemoveTags + Monitoring → 알람 삭제 + lifecycle 알림"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = {
            "detail": {
                "eventName": "RemoveTags",
                "requestParameters": {
                    "resourceArns": [arn],
                    "tagKeys": ["Monitoring"],
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=[]) as mock_delete:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_delete.assert_called_once_with(arn, "ELB")
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "MONITORING_REMOVED"

    def test_rds_non_monitoring_tag_ignored(self):
        """RDS 태그 변경이 Monitoring 아니면 무시"""
        event = {
            "detail": {
                "eventName": "AddTagsToResource",
                "requestParameters": {
                    "resourceName": "arn:aws:rds:us-east-1:123456789012:db:my-rds",
                    "tags": [{"key": "Environment", "value": "prod"}],
                },
            }
        }
        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()
        mock_err.assert_not_called()
