"""
Remediation_Handler 테스트 - Property 9, 10, 12, 14, 15, 16 속성 테스트 + 단위 테스트

Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 8.1~8.7
"""

import logging
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from botocore.exceptions import ClientError

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
    elif event_name == "DeleteTargetGroup":
        params.setdefault("targetGroupArn", resource_id)
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
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "i-001"
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "MODIFY"

    def test_parse_delete_rds(self):
        """RDS DeleteDBInstance 파싱"""
        event = _make_event("DeleteDBInstance", "db-prod")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)):
            parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "db-prod"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "DELETE"

    def test_parse_delete_elb(self):
        """ELB DeleteLoadBalancer 파싱 — app/ ARN → ALB"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("DeleteLoadBalancer", arn)
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "DELETE"

    def test_parse_create_tags(self):
        """CreateTags 파싱"""
        event = _make_event("CreateTags", "i-001")
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "i-001"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_rds_add_tags(self):
        """RDS AddTagsToResource 파싱"""
        event = _make_event("AddTagsToResource", "my-rds-db")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)):
            parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "my-rds-db"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_rds_remove_tags(self):
        """RDS RemoveTagsFromResource 파싱"""
        event = _make_event("RemoveTagsFromResource", "my-rds-db")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)):
            parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "my-rds-db"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_elb_add_tags(self):
        """ELB AddTags 파싱 — app/ ARN → ALB"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("AddTags", arn)
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "TAG_CHANGE"

    def test_parse_elb_remove_tags(self):
        """ELB RemoveTags 파싱 — app/ ARN → ALB"""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = _make_event("RemoveTags", arn)
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == arn
        assert parsed.resource_type == "ALB"
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
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)), \
             patch("remediation_handler.lambda_handler.get_resource_tags",
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
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
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
        assert args[0][1] == "ALB"

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
        mock_delete.assert_called_once_with(arn, "ALB")
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
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = lambda_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()
        mock_err.assert_not_called()


# ──────────────────────────────────────────────
# ALB/NLB resource_type 판별 테스트
# ──────────────────────────────────────────────


class TestAlbNlbResourceType:
    """ARN 기반 ALB/NLB resource_type 판별 및 remediation 검증."""

    def test_parse_delete_alb_returns_alb_type(self):
        """DeleteLoadBalancer + app/ ARN → resource_type='ALB'"""
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = {
            "detail": {
                "eventName": "DeleteLoadBalancer",
                "requestParameters": {"loadBalancerArn": alb_arn},
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "ALB"
        assert parsed.resource_id == alb_arn

    def test_parse_delete_nlb_returns_nlb_type(self):
        """DeleteLoadBalancer + net/ ARN → resource_type='NLB'"""
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        event = {
            "detail": {
                "eventName": "DeleteLoadBalancer",
                "requestParameters": {"loadBalancerArn": nlb_arn},
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "NLB"
        assert parsed.resource_id == nlb_arn

    def test_parse_modify_alb_returns_alb_type(self):
        """ModifyLoadBalancerAttributes + app/ ARN → resource_type='ALB'"""
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = {
            "detail": {
                "eventName": "ModifyLoadBalancerAttributes",
                "requestParameters": {"loadBalancerArn": alb_arn},
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "ALB"

    def test_execute_remediation_alb_calls_delete(self):
        """_execute_remediation('ALB', arn) → elbv2.delete_load_balancer"""
        from remediation_handler.lambda_handler import _execute_remediation
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("remediation_handler.lambda_handler.boto3") as mock_boto3:
            mock_elbv2 = MagicMock()
            mock_boto3.client.return_value = mock_elbv2
            result = _execute_remediation("ALB", alb_arn)
        assert result == "DELETED"
        mock_elbv2.delete_load_balancer.assert_called_once_with(LoadBalancerArn=alb_arn)

    def test_execute_remediation_nlb_calls_delete(self):
        """_execute_remediation('NLB', arn) → elbv2.delete_load_balancer"""
        from remediation_handler.lambda_handler import _execute_remediation
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        with patch("remediation_handler.lambda_handler.boto3") as mock_boto3:
            mock_elbv2 = MagicMock()
            mock_boto3.client.return_value = mock_elbv2
            result = _execute_remediation("NLB", nlb_arn)
        assert result == "DELETED"
        mock_elbv2.delete_load_balancer.assert_called_once_with(LoadBalancerArn=nlb_arn)

    def test_remediation_action_name_alb_nlb(self):
        """_remediation_action_name('ALB'/'NLB') → 'DELETED'"""
        from remediation_handler.lambda_handler import _remediation_action_name
        assert _remediation_action_name("ALB") == "DELETED"
        assert _remediation_action_name("NLB") == "DELETED"

    def test_elb_add_tags_alb_arn_returns_alb_type(self):
        """AddTags + app/ ARN → resource_type='ALB'"""
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        event = {
            "detail": {
                "eventName": "AddTags",
                "requestParameters": {
                    "resourceArns": [alb_arn],
                    "tags": [{"key": "Monitoring", "value": "on"}],
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "ALB"

    def test_elb_add_tags_nlb_arn_returns_nlb_type(self):
        """AddTags + net/ ARN → resource_type='NLB'"""
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        event = {
            "detail": {
                "eventName": "AddTags",
                "requestParameters": {
                    "resourceArns": [nlb_arn],
                    "tags": [{"key": "Monitoring", "value": "on"}],
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "NLB"


# ──────────────────────────────────────────────
# DeleteTargetGroup 버그 수정 단위 테스트
# Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 3.6
# ──────────────────────────────────────────────


class TestDeleteTargetGroup:
    """DeleteTargetGroup 이벤트 처리 버그 수정 검증."""

    TG_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123def456"

    def test_extract_tg_ids_returns_arn(self):
        """_extract_tg_ids(): targetGroupArn 키에서 ARN 추출 확인"""
        from remediation_handler.lambda_handler import _extract_tg_ids
        result = _extract_tg_ids({"targetGroupArn": self.TG_ARN})
        assert result == [self.TG_ARN]

    def test_extract_tg_ids_missing_key_returns_none(self):
        """_extract_tg_ids(): targetGroupArn 키 없을 때 None 반환"""
        from remediation_handler.lambda_handler import _extract_tg_ids
        assert _extract_tg_ids({}) == []
        assert _extract_tg_ids({"loadBalancerArn": "some-arn"}) == []

    def test_get_event_category_delete_target_group(self):
        """_get_event_category('DeleteTargetGroup') → 'DELETE'"""
        from remediation_handler.lambda_handler import _get_event_category
        assert _get_event_category("DeleteTargetGroup") == "DELETE"

    def test_parse_delete_target_group(self):
        """parse_cloudtrail_event(): DeleteTargetGroup → resource_type='TG', event_category='DELETE', resource_id=ARN"""
        event = _make_event("DeleteTargetGroup", self.TG_ARN)
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_type == "TG"
        assert parsed.event_category == "DELETE"
        assert parsed.resource_id == self.TG_ARN

    def test_handle_delete_tg_with_monitoring_tag(self):
        """_handle_delete(): TG + Monitoring=on → delete_alarms_for_resource + send_lifecycle_alert 호출"""
        parsed = _make_parsed("DeleteTargetGroup", self.TG_ARN, "TG", "DELETE")

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=["alarm1"]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        mock_delete.assert_called_once_with(self.TG_ARN, "TG")
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "RESOURCE_DELETED"
        assert mock_alert.call_args.kwargs["resource_id"] == self.TG_ARN

    def test_handle_delete_tg_without_monitoring_tag(self):
        """_handle_delete(): TG + Monitoring 태그 없음 → delete_alarms_for_resource 호출, send_lifecycle_alert 미호출"""
        parsed = _make_parsed("DeleteTargetGroup", self.TG_ARN, "TG", "DELETE")

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={}), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=[]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        mock_delete.assert_called_once_with(self.TG_ARN, "TG")
        mock_alert.assert_not_called()

    def test_template_event_pattern_includes_delete_target_group(self):
        """template.yaml EventPattern에 DeleteTargetGroup 포함 정적 검증"""
        from pathlib import Path

        template_path = Path(__file__).resolve().parent.parent / "template.yaml"
        content = template_path.read_text(encoding="utf-8")

        # CloudTrailModifyRule 섹션에서 DeleteTargetGroup 문자열 존재 확인
        assert "DeleteTargetGroup" in content, (
            "DeleteTargetGroup not found in template.yaml"
        )

        # EventPattern의 eventName 리스트 내에 위치하는지 더 정밀하게 검증
        # CloudTrailModifyRule 블록 추출 후 eventName 리스트에 포함 확인
        import re
        pattern = re.compile(
            r"CloudTrailModifyRule:.*?eventName:\s*\n((?:\s+-\s+\S+\n)+)",
            re.DOTALL,
        )
        match = pattern.search(content)
        assert match, "Could not find CloudTrailModifyRule eventName list"
        event_names_block = match.group(1)
        assert "DeleteTargetGroup" in event_names_block, (
            "DeleteTargetGroup not in CloudTrailModifyRule eventName list"
        )


# ──────────────────────────────────────────────
# CREATE 카테고리 단위 테스트
# Validates: Requirements 1.1, 1.2, 1.3
# ──────────────────────────────────────────────


class TestCreateCategory:
    """MONITORED_API_EVENTS CREATE 카테고리 및 _get_event_category 검증."""

    def test_monitored_api_events_has_create_key(self):
        """MONITORED_API_EVENTS에 'CREATE' 키가 존재해야 한다."""
        from common import MONITORED_API_EVENTS
        assert "CREATE" in MONITORED_API_EVENTS, (
            "MONITORED_API_EVENTS should contain 'CREATE' key"
        )

    def test_create_category_contains_four_events(self):
        """CREATE 카테고리에 6개 이벤트가 포함되어야 한다."""
        from common import MONITORED_API_EVENTS
        expected = {"RunInstances", "CreateDBInstance", "CreateLoadBalancer", "CreateTargetGroup", "CreateCacheCluster", "CreateNatGateway"}
        actual = set(MONITORED_API_EVENTS.get("CREATE", []))
        assert actual == expected, (
            f"CREATE category should contain {expected}, got {actual}"
        )

    def test_existing_categories_preserved(self):
        """기존 MODIFY, DELETE, TAG_CHANGE 카테고리가 보존되어야 한다."""
        from common import MONITORED_API_EVENTS
        for category in ("MODIFY", "DELETE", "TAG_CHANGE"):
            assert category in MONITORED_API_EVENTS, (
                f"Existing category '{category}' should be preserved"
            )
            assert len(MONITORED_API_EVENTS[category]) > 0, (
                f"Category '{category}' should not be empty"
            )

    def test_get_event_category_run_instances_returns_create(self):
        """_get_event_category('RunInstances') → 'CREATE'"""
        from remediation_handler.lambda_handler import _get_event_category
        assert _get_event_category("RunInstances") == "CREATE"

    def test_get_event_category_create_db_instance_returns_create(self):
        """_get_event_category('CreateDBInstance') → 'CREATE'"""
        from remediation_handler.lambda_handler import _get_event_category
        assert _get_event_category("CreateDBInstance") == "CREATE"


# ──────────────────────────────────────────────
# CREATE용 ID 추출 함수 단위 테스트
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
# ──────────────────────────────────────────────


class TestCreateIdExtractors:
    """CREATE 이벤트용 ID 추출 함수 개별 테스트."""

    def test_extract_run_instances_ids_normal(self):
        """_extract_run_instances_ids: instancesSet.items[0].instanceId 추출"""
        from remediation_handler.lambda_handler import _extract_run_instances_ids
        resp = {"instancesSet": {"items": [{"instanceId": "i-abc"}]}}
        assert _extract_run_instances_ids(resp) == ["i-abc"]

    def test_extract_run_instances_ids_empty_items(self):
        """_extract_run_instances_ids: 빈 items → None"""
        from remediation_handler.lambda_handler import _extract_run_instances_ids
        resp = {"instancesSet": {"items": []}}
        assert _extract_run_instances_ids(resp) == []

    def test_extract_create_db_ids_normal(self):
        """_extract_create_db_ids: dBInstanceIdentifier 추출"""
        from remediation_handler.lambda_handler import _extract_create_db_ids
        params = {"dBInstanceIdentifier": "mydb"}
        assert _extract_create_db_ids(params) == ["mydb"]

    def test_extract_create_lb_ids_normal(self):
        """_extract_create_lb_ids: loadBalancers[0].loadBalancerArn 추출"""
        from remediation_handler.lambda_handler import _extract_create_lb_ids
        resp = {"loadBalancers": [{"loadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"}]}
        assert _extract_create_lb_ids(resp) == ["arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"]

    def test_extract_create_lb_ids_empty_list(self):
        """_extract_create_lb_ids: 빈 loadBalancers → None"""
        from remediation_handler.lambda_handler import _extract_create_lb_ids
        resp = {"loadBalancers": []}
        assert _extract_create_lb_ids(resp) == []

    def test_extract_create_tg_ids_normal(self):
        """_extract_create_tg_ids: targetGroups[0].targetGroupArn 추출"""
        from remediation_handler.lambda_handler import _extract_create_tg_ids
        resp = {"targetGroups": [{"targetGroupArn": "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc"}]}
        assert _extract_create_tg_ids(resp) == ["arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc"]

    def test_extract_create_tg_ids_empty_list(self):
        """_extract_create_tg_ids: 빈 targetGroups → None"""
        from remediation_handler.lambda_handler import _extract_create_tg_ids
        resp = {"targetGroups": []}
        assert _extract_create_tg_ids(resp) == []


# ──────────────────────────────────────────────
# CREATE 이벤트 파싱 단위 테스트 (parse_cloudtrail_event)
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.2, 6.3
# ──────────────────────────────────────────────


class TestCreateEventParsing:
    """parse_cloudtrail_event()가 CREATE 이벤트의 responseElements에서 리소스 ID를 올바르게 추출하는지 검증."""

    def test_run_instances_parses_ec2(self):
        """RunInstances → resource_type='EC2', event_category='CREATE', resource_id from responseElements"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {"instanceType": "t3.micro"},
                "responseElements": {
                    "instancesSet": {"items": [{"instanceId": "i-abc123"}]}
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "i-abc123"
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "CREATE"

    def test_create_db_instance_parses_rds(self):
        """CreateDBInstance → resource_type='RDS', event_category='CREATE', resource_id from requestParameters"""
        event = {
            "detail": {
                "eventName": "CreateDBInstance",
                "requestParameters": {"dBInstanceIdentifier": "mydb-prod"},
                "responseElements": {},
            }
        }
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type", return_value=("RDS", False)):
            parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == "mydb-prod"
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "CREATE"

    def test_create_load_balancer_alb_parses(self):
        """CreateLoadBalancer + app/ ARN → resource_type='ALB', event_category='CREATE'"""
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        event = {
            "detail": {
                "eventName": "CreateLoadBalancer",
                "requestParameters": {"name": "my-alb", "type": "application"},
                "responseElements": {
                    "loadBalancers": [{"loadBalancerArn": alb_arn}]
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == alb_arn
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "CREATE"

    def test_create_load_balancer_nlb_parses(self):
        """CreateLoadBalancer + net/ ARN → resource_type='NLB', event_category='CREATE'"""
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        event = {
            "detail": {
                "eventName": "CreateLoadBalancer",
                "requestParameters": {"name": "my-nlb", "type": "network"},
                "responseElements": {
                    "loadBalancers": [{"loadBalancerArn": nlb_arn}]
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == nlb_arn
        assert parsed.resource_type == "NLB"
        assert parsed.event_category == "CREATE"

    def test_create_target_group_parses(self):
        """CreateTargetGroup → resource_type='TG', event_category='CREATE'"""
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        event = {
            "detail": {
                "eventName": "CreateTargetGroup",
                "requestParameters": {"name": "my-tg"},
                "responseElements": {
                    "targetGroups": [{"targetGroupArn": tg_arn}]
                },
            }
        }
        parsed = parse_cloudtrail_event(event)[0]
        assert parsed.resource_id == tg_arn
        assert parsed.resource_type == "TG"
        assert parsed.event_category == "CREATE"

    def test_run_instances_missing_response_elements_raises(self):
        """RunInstances + responseElements 누락 → ValueError"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {"instanceType": "t3.micro"},
            }
        }
        with pytest.raises(ValueError, match="Cannot extract resource_id"):
            parse_cloudtrail_event(event)

    def test_create_load_balancer_empty_list_raises(self):
        """CreateLoadBalancer + 빈 loadBalancers 리스트 → ValueError"""
        event = {
            "detail": {
                "eventName": "CreateLoadBalancer",
                "requestParameters": {"name": "my-alb"},
                "responseElements": {
                    "loadBalancers": []
                },
            }
        }
        with pytest.raises(ValueError, match="Cannot extract resource_id"):
            parse_cloudtrail_event(event)


# ──────────────────────────────────────────────
# _handle_create 핸들러 및 lambda_handler CREATE 라우팅 단위 테스트
# Validates: Requirements 4.1, 4.2, 4.3, 4.4, 7.1, 7.2, 7.3
# ──────────────────────────────────────────────


class TestHandleCreate:
    """_handle_create 핸들러 및 lambda_handler CREATE 라우팅 검증."""

    def _make_create_parsed(self, resource_id="i-new123", resource_type="EC2",
                            event_name="RunInstances"):
        """CREATE ParsedEvent 헬퍼."""
        return ParsedEvent(
            resource_id=resource_id,
            resource_type=resource_type,
            event_name=event_name,
            event_category="CREATE",
            change_summary=f"{event_name} on {resource_type} {resource_id}",
            request_params={},
        )

    # ── 라우팅 테스트 ──

    def test_create_event_routes_to_handle_create(self):
        """CREATE 이벤트 → _handle_create 호출 확인 (라우팅) — Requirements 7.1"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {"instanceType": "t3.micro"},
                "responseElements": {
                    "instancesSet": {"items": [{"instanceId": "i-new123"}]}
                },
            }
        }
        with patch("remediation_handler.lambda_handler._handle_create") as mock_hc:
            result = lambda_handler(event, MagicMock())

        mock_hc.assert_called_once()
        assert result["status"] == "ok"

    # ── Monitoring=on → create_alarms_for_resource 호출 ──

    def test_create_with_monitoring_on_creates_alarms(self):
        """CREATE + Monitoring=on → create_alarms_for_resource 호출 — Requirements 4.1"""
        from remediation_handler.lambda_handler import _handle_create

        parsed = self._make_create_parsed()
        tags = {"Monitoring": "on", "Name": "test-instance"}

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=tags) as mock_tags, \
             patch("remediation_handler.lambda_handler.has_monitoring_tag",
                   return_value=True), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                   return_value=["alarm1"]) as mock_create:
            _handle_create(parsed)

        mock_tags.assert_called_once_with("i-new123", "EC2")
        mock_create.assert_called_once_with("i-new123", "EC2", tags)

    # ── Monitoring 태그 없음 → 알람 생성 미호출 + info 로그 ──

    def test_create_without_monitoring_tag_skips_alarms(self, caplog):
        """CREATE + Monitoring 태그 없음 → create_alarms_for_resource 미호출 + info 로그 — Requirements 4.2"""
        from remediation_handler.lambda_handler import _handle_create

        parsed = self._make_create_parsed()
        tags = {"Name": "test-instance"}

        with caplog.at_level(logging.INFO, logger="remediation_handler.lambda_handler"), \
             patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value=tags), \
             patch("remediation_handler.lambda_handler.has_monitoring_tag",
                   return_value=False), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource") as mock_create:
            _handle_create(parsed)

        mock_create.assert_not_called()
        log_msgs = [r.message for r in caplog.records]
        assert any("skip" in m.lower() or "Skipping" in m for m in log_msgs), \
            f"Expected info log about skipping alarm creation, got: {log_msgs}"

    # ── get_resource_tags 빈 딕셔너리 → warning 로그 + 스킵 ──

    def test_create_empty_tags_logs_warning_and_skips(self, caplog):
        """CREATE + get_resource_tags 빈 딕셔너리 → warning 로그 + 알람 생성 스킵 — Requirements 4.4"""
        from remediation_handler.lambda_handler import _handle_create

        parsed = self._make_create_parsed()

        with caplog.at_level(logging.WARNING, logger="remediation_handler.lambda_handler"), \
             patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={}) as mock_tags, \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource") as mock_create:
            _handle_create(parsed)

        mock_tags.assert_called_once_with("i-new123", "EC2")
        mock_create.assert_not_called()
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_msgs, "Expected warning log when get_resource_tags returns empty dict"

    # ── 정상 처리 → {"status": "ok"} ──

    def test_create_event_returns_ok(self):
        """CREATE 이벤트 정상 처리 → {"status": "ok"} 반환 — Requirements 7.2"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {"instanceType": "t3.micro"},
                "responseElements": {
                    "instancesSet": {"items": [{"instanceId": "i-new123"}]}
                },
            }
        }
        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.has_monitoring_tag",
                   return_value=True), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                   return_value=["alarm1"]):
            result = lambda_handler(event, MagicMock())

        assert result == {"status": "ok"}

    # ── 예외 발생 → {"status": "error"} ──

    def test_create_event_exception_returns_error(self):
        """CREATE 이벤트 처리 중 예외 → {"status": "error"} 반환 — Requirements 7.3"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {"instanceType": "t3.micro"},
                "responseElements": {
                    "instancesSet": {"items": [{"instanceId": "i-new123"}]}
                },
            }
        }
        with patch("remediation_handler.lambda_handler._handle_create",
                   side_effect=RuntimeError("boom")):
            result = lambda_handler(event, MagicMock())

        assert result == {"status": "error"}


# ──────────────────────────────────────────────
# EventBridge 규칙 정적 검증 테스트
# Validates: Requirements 2.1, 2.2
# ──────────────────────────────────────────────


class TestEventBridgeRule:
    """template.yaml CloudTrailModifyRule EventPattern에 CREATE 이벤트 포함 및 기존 이벤트 보존 검증."""

    @staticmethod
    def _load_event_names() -> list[str]:
        """template.yaml을 파싱하여 CloudTrailModifyRule의 eventName 리스트를 반환."""
        from pathlib import Path
        import yaml

        # CloudFormation 인트린식 함수 태그를 처리하는 커스텀 로더
        class _CfnLoader(yaml.SafeLoader):
            pass

        def _cfn_tag_constructor(loader, tag_suffix, node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            if isinstance(node, yaml.MappingNode):
                return loader.construct_mapping(node)
            return None

        _CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)

        template_path = Path(__file__).resolve().parent.parent / "template.yaml"
        with open(template_path, encoding="utf-8") as f:
            template = yaml.load(f, Loader=_CfnLoader)

        return (
            template["Resources"]["CloudTrailModifyRule"]
            ["Properties"]["EventPattern"]["detail"]["eventName"]
        )

    def test_event_pattern_includes_create_events(self):
        """CloudTrailModifyRule EventPattern에 4개 CREATE 이벤트가 포함되어야 한다 — Requirements 2.1"""
        event_names = self._load_event_names()
        expected_create_events = [
            "RunInstances",
            "CreateDBInstance",
            "CreateLoadBalancer",
            "CreateTargetGroup",
        ]
        for event_name in expected_create_events:
            assert event_name in event_names, (
                f"CREATE event '{event_name}' not found in CloudTrailModifyRule eventName list. "
                f"Current list: {event_names}"
            )

    def test_event_pattern_preserves_existing_events(self):
        """기존 MODIFY/DELETE/TAG_CHANGE 이벤트 필터가 보존되어야 한다 — Requirements 2.2"""
        event_names = self._load_event_names()
        existing_events = [
            # MODIFY
            "ModifyInstanceAttribute",
            "ModifyInstanceType",
            "ModifyDBInstance",
            "ModifyLoadBalancerAttributes",
            "ModifyListener",
            # DELETE
            "TerminateInstances",
            "DeleteDBInstance",
            "DeleteLoadBalancer",
            "DeleteTargetGroup",
            # TAG_CHANGE
            "CreateTags",
            "DeleteTags",
            "AddTagsToResource",
            "RemoveTagsFromResource",
            "AddTags",
            "RemoveTags",
        ]
        for event_name in existing_events:
            assert event_name in event_names, (
                f"Existing event '{event_name}' missing from CloudTrailModifyRule eventName list. "
                f"Current list: {event_names}"
            )


# ──────────────────────────────────────────────
# _resolve_rds_aurora_type() 헬퍼 테스트
# Validates: Requirements 9.5
# ──────────────────────────────────────────────


class TestResolveRdsAuroraType:
    """_resolve_rds_aurora_type() 헬퍼 검증."""

    def test_aurora_mysql_engine_returns_aurora_rds(self):
        """Engine 'aurora-mysql' → 'AuroraRDS' 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "aurora-mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-aurora-db")

        assert result == ("AuroraRDS", False)
        mock_rds.describe_db_instances.assert_called_once_with(
            DBInstanceIdentifier="my-aurora-db"
        )

    def test_aurora_postgresql_engine_returns_aurora_rds(self):
        """Engine 'aurora-postgresql' → 'AuroraRDS' 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "aurora-postgresql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-aurora-pg")

        assert result == ("AuroraRDS", False)

    def test_mysql_engine_returns_rds(self):
        """Engine 'mysql' → 'RDS' 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-mysql-db")

        assert result == ("RDS", False)

    def test_postgres_engine_returns_rds(self):
        """Engine 'postgres' → 'RDS' 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "postgres"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-pg-db")

        assert result == ("RDS", False)

    def test_api_error_falls_back_to_rds(self, caplog):
        """ClientError 발생 시 'RDS' 폴백 + warning 로그"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.side_effect = ClientError(
            {"Error": {"Code": "DBInstanceNotFound", "Message": "not found"}},
            "DescribeDBInstances",
        )
        with caplog.at_level(logging.WARNING, logger="remediation_handler.lambda_handler"), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("nonexistent-db")

        assert result == ("RDS", True)
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_msgs, "Expected warning log on API error fallback"


# ──────────────────────────────────────────────
# parse_cloudtrail_event() Aurora RDS 이벤트 검증
# Validates: Requirements 9.1, 9.2, 9.3, 9.4
# ──────────────────────────────────────────────


class TestParseCloudTrailAuroraRds:
    """parse_cloudtrail_event()가 Aurora RDS 이벤트를 올바르게 AuroraRDS로 해석하는지 검증."""

    def _mock_resolve_aurora(self):
        """_resolve_rds_aurora_type → ('AuroraRDS', False) 반환 mock."""
        return patch(
            "remediation_handler.lambda_handler._resolve_rds_aurora_type",
            return_value=("AuroraRDS", False),
        )

    def _mock_resolve_rds(self):
        """_resolve_rds_aurora_type → ('RDS', False) 반환 mock."""
        return patch(
            "remediation_handler.lambda_handler._resolve_rds_aurora_type",
            return_value=("RDS", False),
        )

    def test_create_db_instance_aurora_resolves_aurora_rds(self):
        """CreateDBInstance (Aurora engine) → resource_type='AuroraRDS' — Requirements 9.1"""
        event = {
            "detail": {
                "eventName": "CreateDBInstance",
                "requestParameters": {"dBInstanceIdentifier": "my-aurora-db"},
            }
        }
        with self._mock_resolve_aurora() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "AuroraRDS"
        assert parsed.resource_id == "my-aurora-db"
        assert parsed.event_category == "CREATE"
        mock_resolve.assert_called_once_with("my-aurora-db")

    def test_delete_db_instance_aurora_resolves_aurora_rds(self):
        """DeleteDBInstance (Aurora engine) → resource_type='AuroraRDS' — Requirements 9.2"""
        event = _make_event("DeleteDBInstance", "my-aurora-db")
        with self._mock_resolve_aurora() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "AuroraRDS"
        assert parsed.resource_id == "my-aurora-db"
        assert parsed.event_category == "DELETE"
        mock_resolve.assert_called_once_with("my-aurora-db")

    def test_modify_db_instance_aurora_resolves_aurora_rds(self):
        """ModifyDBInstance (Aurora engine) → resource_type='AuroraRDS' — Requirements 9.3"""
        event = _make_event("ModifyDBInstance", "my-aurora-db")
        with self._mock_resolve_aurora() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "AuroraRDS"
        assert parsed.resource_id == "my-aurora-db"
        assert parsed.event_category == "MODIFY"
        mock_resolve.assert_called_once_with("my-aurora-db")

    def test_add_tags_to_resource_aurora_resolves_aurora_rds(self):
        """AddTagsToResource (Aurora engine) → resource_type='AuroraRDS' — Requirements 9.4"""
        event = _make_event("AddTagsToResource", "my-aurora-db")
        with self._mock_resolve_aurora() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "AuroraRDS"
        assert parsed.resource_id == "my-aurora-db"
        assert parsed.event_category == "TAG_CHANGE"
        mock_resolve.assert_called_once_with("my-aurora-db")

    def test_remove_tags_from_resource_aurora_resolves_aurora_rds(self):
        """RemoveTagsFromResource (Aurora engine) → resource_type='AuroraRDS' — Requirements 9.4"""
        event = _make_event("RemoveTagsFromResource", "my-aurora-db")
        with self._mock_resolve_aurora() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "AuroraRDS"
        assert parsed.resource_id == "my-aurora-db"
        assert parsed.event_category == "TAG_CHANGE"
        mock_resolve.assert_called_once_with("my-aurora-db")

    def test_create_db_instance_non_aurora_stays_rds(self):
        """CreateDBInstance (non-Aurora engine) → resource_type='RDS' 유지"""
        event = {
            "detail": {
                "eventName": "CreateDBInstance",
                "requestParameters": {"dBInstanceIdentifier": "my-mysql-db"},
            }
        }
        with self._mock_resolve_rds() as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "RDS"
        mock_resolve.assert_called_once_with("my-mysql-db")

    def test_ec2_event_does_not_call_resolve(self):
        """EC2 이벤트는 _resolve_rds_aurora_type 호출하지 않음"""
        event = _make_event("ModifyInstanceAttribute", "i-001")
        with patch(
            "remediation_handler.lambda_handler._resolve_rds_aurora_type"
        ) as mock_resolve:
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_type == "EC2"
        mock_resolve.assert_not_called()


# ──────────────────────────────────────────────
# KI-008: Aurora 삭제 이벤트 알람 정리 검증
# Validates: Requirements 13.1, 13.2, 13.3
# ──────────────────────────────────────────────


class TestResolveRdsAuroraTypeTuple:
    """_resolve_rds_aurora_type() 튜플 반환 검증 (KI-008)."""

    def test_aurora_engine_returns_tuple_no_fallback(self):
        """Aurora engine → ('AuroraRDS', False) 튜플 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "aurora-mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-aurora-db")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert result == ("AuroraRDS", False)

    def test_rds_engine_returns_tuple_no_fallback(self):
        """Non-Aurora engine → ('RDS', False) 튜플 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("my-mysql-db")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert result == ("RDS", False)

    def test_api_error_returns_tuple_with_fallback(self, caplog):
        """ClientError → ('RDS', True) 폴백 튜플 + warning 로그"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.side_effect = ClientError(
            {"Error": {"Code": "DBInstanceNotFound", "Message": "not found"}},
            "DescribeDBInstances",
        )
        with caplog.at_level(logging.WARNING, logger="remediation_handler.lambda_handler"), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("deleted-db")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert result == ("RDS", True)
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_msgs, "Expected warning log on API error fallback"


class TestHandleDeleteAuroraFallback:
    """_handle_delete() Aurora 삭제 이벤트 알람 정리 검증 (KI-008)."""

    def test_delete_with_fallback_calls_empty_resource_type(self):
        """is_fallback=True + DELETE → delete_alarms_for_resource(resource_id, '') 호출"""
        parsed = ParsedEvent(
            resource_id="my-aurora-db",
            resource_type="RDS",
            event_name="DeleteDBInstance",
            event_category="DELETE",
            change_summary="DeleteDBInstance on RDS my-aurora-db",
            request_params={},
            _is_rds_fallback=True,
        )

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={}) as mock_tags, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=[]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        # is_fallback=True → resource_type="" 으로 호출하여 전체 prefix 검색
        mock_delete.assert_called_once_with("my-aurora-db", "")

    def test_delete_without_fallback_uses_original_type(self):
        """is_fallback=False + DELETE → delete_alarms_for_resource(resource_id, resource_type) 호출"""
        parsed = ParsedEvent(
            resource_id="my-aurora-db",
            resource_type="AuroraRDS",
            event_name="DeleteDBInstance",
            event_category="DELETE",
            change_summary="DeleteDBInstance on AuroraRDS my-aurora-db",
            request_params={},
            _is_rds_fallback=False,
        )

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}) as mock_tags, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=["alarm1"]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        # is_fallback=False → 원래 resource_type 사용
        mock_delete.assert_called_once_with("my-aurora-db", "AuroraRDS")

    def test_delete_fallback_with_alarms_found_sends_lifecycle_alert(self):
        """is_fallback=True + 알람 발견 → lifecycle 알림 발송"""
        parsed = ParsedEvent(
            resource_id="my-aurora-db",
            resource_type="RDS",
            event_name="DeleteDBInstance",
            event_category="DELETE",
            change_summary="DeleteDBInstance on RDS my-aurora-db",
            request_params={},
            _is_rds_fallback=True,
        )

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   side_effect=Exception("instance deleted")), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=["[AuroraRDS] my-aurora-db CPU"]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        mock_delete.assert_called_once_with("my-aurora-db", "")
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "RESOURCE_DELETED"

    def test_delete_fallback_warning_log(self, caplog):
        """is_fallback=True → warning 로그 출력"""
        parsed = ParsedEvent(
            resource_id="my-aurora-db",
            resource_type="RDS",
            event_name="DeleteDBInstance",
            event_category="DELETE",
            change_summary="DeleteDBInstance on RDS my-aurora-db",
            request_params={},
            _is_rds_fallback=True,
        )

        with caplog.at_level(logging.WARNING, logger="remediation_handler.lambda_handler"), \
             patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={}) as mock_tags, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert"), \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=[]):
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("fallback" in m.lower() or "prefix" in m.lower() for m in warning_msgs), \
            f"Expected warning about fallback/prefix search, got: {warning_msgs}"

    def test_non_rds_delete_no_fallback_field(self):
        """EC2 DELETE 이벤트 → _is_rds_fallback=False (기본값)"""
        parsed = ParsedEvent(
            resource_id="i-001",
            resource_type="EC2",
            event_name="TerminateInstances",
            event_category="DELETE",
            change_summary="TerminateInstances on EC2 i-001",
            request_params={},
        )

        # _is_rds_fallback 기본값은 False
        assert parsed._is_rds_fallback is False

        with patch("remediation_handler.lambda_handler.get_resource_tags",
                   return_value={"Monitoring": "on"}) as mock_tags, \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                   return_value=["alarm1"]) as mock_delete:
            from remediation_handler.lambda_handler import _handle_delete
            _handle_delete(parsed)

        # EC2는 원래 resource_type 사용
        mock_delete.assert_called_once_with("i-001", "EC2")


# ──────────────────────────────────────────────
# Task 9.1: Remediation Handler DocDB 지원 테스트
# Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 14.1, 14.2, 14.3
# ──────────────────────────────────────────────


class TestDocDBRemediation:
    """Remediation Handler DocDB 지원 검증."""

    def test_resolve_docdb_engine_returns_docdb(self):
        """Engine 'docdb' → ('DocDB', False) 반환 — Req 10.5"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "docdb"}],
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("docdb-prod-1")

        assert result == ("DocDB", False)

    def test_resolve_docdb_before_aurora(self):
        """DocDB 판별이 Aurora 판별보다 먼저 실행 — Req 10.5"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        # 'docdb' contains no 'aurora' substring, but verify ordering is correct
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "docdb"}],
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("docdb-inst-1")

        assert result[0] == "DocDB"

    def test_aurora_still_returns_aurora_rds(self):
        """DocDB 추가 후에도 Aurora 엔진은 여전히 AuroraRDS 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "aurora-mysql"}],
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("aurora-db-1")

        assert result == ("AuroraRDS", False)

    def test_mysql_still_returns_rds(self):
        """DocDB 추가 후에도 MySQL 엔진은 여전히 RDS 반환"""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "mysql"}],
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _resolve_rds_aurora_type("mysql-db-1")

        assert result == ("RDS", False)

    def test_execute_remediation_docdb_calls_stop(self):
        """_execute_remediation('DocDB', id) → stop_db_instance + 'STOPPED' — Req 14.2"""
        from remediation_handler.lambda_handler import _execute_remediation

        mock_rds = MagicMock()
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            result = _execute_remediation("DocDB", "docdb-prod-1")

        assert result == "STOPPED"
        mock_rds.stop_db_instance.assert_called_once_with(
            DBInstanceIdentifier="docdb-prod-1",
        )

    def test_remediation_action_name_docdb(self):
        """_remediation_action_name('DocDB') → 'STOPPED' — Req 14.3"""
        from remediation_handler.lambda_handler import _remediation_action_name
        assert _remediation_action_name("DocDB") == "STOPPED"

    def test_parse_create_db_instance_docdb_engine(self):
        """CreateDBInstance + Engine 'docdb' → resource_type='DocDB' — Req 10.1"""
        event = {
            "detail": {
                "eventName": "CreateDBInstance",
                "requestParameters": {"dBInstanceIdentifier": "docdb-new-1"},
                "responseElements": {},
            }
        }
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type",
                   return_value=("DocDB", False)):
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_id == "docdb-new-1"
        assert parsed.resource_type == "DocDB"
        assert parsed.event_category == "CREATE"

    def test_parse_delete_db_instance_docdb(self):
        """DeleteDBInstance + DocDB → resource_type='DocDB' — Req 10.2"""
        event = _make_event("DeleteDBInstance", "docdb-del-1")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type",
                   return_value=("DocDB", False)):
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_id == "docdb-del-1"
        assert parsed.resource_type == "DocDB"
        assert parsed.event_category == "DELETE"

    def test_parse_modify_db_instance_docdb(self):
        """ModifyDBInstance + DocDB → resource_type='DocDB' — Req 10.3"""
        event = _make_event("ModifyDBInstance", "docdb-mod-1")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type",
                   return_value=("DocDB", False)):
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_id == "docdb-mod-1"
        assert parsed.resource_type == "DocDB"
        assert parsed.event_category == "MODIFY"

    def test_parse_add_tags_docdb(self):
        """AddTagsToResource + DocDB → resource_type='DocDB' — Req 10.4"""
        event = _make_event("AddTagsToResource", "docdb-tag-1")
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type",
                   return_value=("DocDB", False)):
            parsed = parse_cloudtrail_event(event)[0]

        assert parsed.resource_id == "docdb-tag-1"
        assert parsed.resource_type == "DocDB"
        assert parsed.event_category == "TAG_CHANGE"
