"""
remediation_handler.lambda_handler 단위 테스트 (Phase 1.5.2)

커버 케이스:
- parse_cloudtrail_event: EC2/RDS/ELB 이벤트 파싱, ALB/NLB 타입 세분화
- Aurora fallback (KI-008): describe_db_instances 실패 시 RDS 폴백 + is_rds_fallback=True
- _extract_id_from_arn: DynamoDB/SNS/MSK/Lambda ARN 변환
- _handle_delete: 알람 삭제 + lifecycle 알림 흐름
- _handle_tag_change: Monitoring 추가/제거, Threshold 변경
- lambda_handler: 정상 흐름, 파싱 오류, 알 수 없는 이벤트
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


_ENV = {
    "ENVIRONMENT": "test",
    "SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:123456789012:test-alerts",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
}


def _ct_event(event_name: str, request_params: dict, response_elements: dict = None) -> dict:
    """CloudTrail EventBridge 래핑 이벤트 생성 헬퍼."""
    detail: dict = {
        "eventName": event_name,
        "requestParameters": request_params,
    }
    if response_elements is not None:
        detail["responseElements"] = response_elements
    return {"detail": detail}


# ──────────────────────────────────────────────
# parse_cloudtrail_event — 이벤트 파싱
# ──────────────────────────────────────────────

class TestParseCloudtrailEvent:
    """이벤트 파싱 기본 동작 검증."""

    def test_terminate_instances_returns_ec2_delete(self):
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        event = _ct_event(
            "TerminateInstances",
            {"instancesSet": {"items": [{"instanceId": "i-0abc1234"}]}},
        )
        with patch("remediation_handler.lambda_handler._resolve_rds_aurora_type"):
            results = parse_cloudtrail_event(event)

        assert len(results) == 1
        p = results[0]
        assert p.resource_id == "i-0abc1234"
        assert p.resource_type == "EC2"
        assert p.event_category == "DELETE"

    def test_terminate_multiple_instances(self):
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        event = _ct_event(
            "TerminateInstances",
            {"instancesSet": {"items": [
                {"instanceId": "i-001"},
                {"instanceId": "i-002"},
            ]}},
        )
        results = parse_cloudtrail_event(event)
        assert len(results) == 2
        assert {r.resource_id for r in results} == {"i-001", "i-002"}

    def test_create_load_balancer_alb_type(self):
        """LoadBalancerArn에 /app/ 포함 → ALB 타입 세분화."""
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123"
        event = _ct_event(
            "CreateLoadBalancer",
            {},
            {"loadBalancers": [{"loadBalancerArn": arn}]},
        )
        results = parse_cloudtrail_event(event)
        assert results[0].resource_type == "ALB"

    def test_create_load_balancer_nlb_type(self):
        """LoadBalancerArn에 /net/ 포함 → NLB 타입 세분화."""
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/def456"
        event = _ct_event(
            "CreateLoadBalancer",
            {},
            {"loadBalancers": [{"loadBalancerArn": arn}]},
        )
        results = parse_cloudtrail_event(event)
        assert results[0].resource_type == "NLB"

    def test_missing_event_name_raises_value_error(self):
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        with pytest.raises(ValueError, match="eventName"):
            parse_cloudtrail_event({"detail": {}})

    def test_unsupported_event_name_raises_value_error(self):
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        event = _ct_event("SomeUnknownEvent", {})
        with pytest.raises(ValueError, match="Unsupported"):
            parse_cloudtrail_event(event)

    def test_ec2_create_tags_returns_tag_change(self):
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        event = _ct_event(
            "CreateTags",
            {
                "resourcesSet": {"items": [{"resourceId": "i-0abc1234"}]},
                "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]},
            },
        )
        results = parse_cloudtrail_event(event)
        assert results[0].event_category == "TAG_CHANGE"
        assert results[0].resource_id == "i-0abc1234"

    def test_run_instances_uses_response_elements(self):
        """RunInstances: responseElements에서 ID 추출."""
        from remediation_handler.lambda_handler import parse_cloudtrail_event

        event = _ct_event(
            "RunInstances",
            {},
            {"instancesSet": {"items": [{"instanceId": "i-newinstance"}]}},
        )
        results = parse_cloudtrail_event(event)
        assert results[0].resource_id == "i-newinstance"
        assert results[0].event_category == "CREATE"


# ──────────────────────────────────────────────
# Aurora fallback (KI-008)
# ──────────────────────────────────────────────

class TestAuroraFallback:
    """KI-008: describe_db_instances 실패 시 RDS 폴백."""

    def test_rds_engine_returns_rds_type(self):
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            rtype, fallback = _resolve_rds_aurora_type("my-db")

        assert rtype == "RDS"
        assert fallback is False

    def test_aurora_engine_returns_aurora_type(self):
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "aurora-mysql"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            rtype, fallback = _resolve_rds_aurora_type("my-cluster")

        assert rtype == "AuroraRDS"
        assert fallback is False

    def test_docdb_engine_returns_docdb_type(self):
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"Engine": "docdb"}]
        }
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            rtype, fallback = _resolve_rds_aurora_type("my-docdb")

        assert rtype == "DocDB"
        assert fallback is False

    def test_api_error_returns_rds_fallback(self):
        """ClientError 발생 시 ("RDS", True) 반환 — KI-008 폴백."""
        from remediation_handler.lambda_handler import _resolve_rds_aurora_type

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.side_effect = ClientError(
            {"Error": {"Code": "DBInstanceNotFound", "Message": "Not found"}},
            "DescribeDBInstances",
        )
        with patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds):
            rtype, fallback = _resolve_rds_aurora_type("deleted-db")

        assert rtype == "RDS"
        assert fallback is True

    def test_delete_db_event_with_fallback_uses_empty_delete_type(self):
        """DeleteDBInstance 이벤트 + Aurora 판별 실패 → delete_type="" 로 전체 prefix 검색."""
        from remediation_handler import lambda_handler as lh

        event = _ct_event(
            "DeleteDBInstance",
            {"dBInstanceIdentifier": "my-db"},
        )

        mock_rds_client = MagicMock()
        mock_rds_client.describe_db_instances.side_effect = ClientError(
            {"Error": {"Code": "DBInstanceNotFound", "Message": "Not found"}},
            "DescribeDBInstances",
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds_client),
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]) as mock_del,
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert"),
                patch("remediation_handler.lambda_handler.send_error_alert"),
            ):
                result = lh.lambda_handler(event, None)

        # delete_alarms_for_resource가 빈 resource_type으로 호출됨
        call_args = mock_del.call_args
        assert call_args[0][1] == ""  # delete_type=""
        assert result["status"] == "ok"


# ──────────────────────────────────────────────
# _extract_id_from_arn — ARN 변환
# ──────────────────────────────────────────────

class TestExtractIdFromArn:
    """TagResource/UntagResource ARN → resource_id 변환."""

    def test_dynamodb_table_arn(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:dynamodb:ap-northeast-2:123456789012:table/my-table"
        assert _extract_id_from_arn(arn, "DynamoDB") == "my-table"

    def test_sns_topic_arn(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:sns:ap-northeast-2:123456789012:my-topic"
        assert _extract_id_from_arn(arn, "SNS") == "my-topic"

    def test_msk_cluster_arn(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:kafka:ap-northeast-2:123456789012:cluster/my-cluster/abc-uuid"
        assert _extract_id_from_arn(arn, "MSK") == "my-cluster"

    def test_efs_file_system_arn(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:elasticfilesystem:ap-northeast-2:123456789012:file-system/fs-0abc1234"
        assert _extract_id_from_arn(arn, "EFS") == "fs-0abc1234"

    def test_lambda_arn_unchanged(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:lambda:ap-northeast-2:123456789012:function:my-func"
        assert _extract_id_from_arn(arn, "Lambda") == arn

    def test_acm_arn_unchanged(self):
        from remediation_handler.lambda_handler import _extract_id_from_arn

        arn = "arn:aws:acm:ap-northeast-2:123456789012:certificate/abc-uuid"
        assert _extract_id_from_arn(arn, "ACM") == arn


# ──────────────────────────────────────────────
# _handle_delete — 삭제 이벤트 처리
# ──────────────────────────────────────────────

class TestHandleDelete:
    """DELETE 이벤트: 알람 삭제 + lifecycle 알림."""

    def test_monitored_resource_sends_lifecycle_alert(self):
        """Monitoring=on 태그 → lifecycle 알림 발송."""
        from remediation_handler.lambda_handler import _handle_delete, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0abc1234",
            resource_type="EC2",
            event_name="TerminateInstances",
            event_category="DELETE",
            change_summary="terminate",
            request_params={},
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=["alarm1"]),
                patch("remediation_handler.lambda_handler.get_resource_tags",
                      return_value={"Monitoring": "on", "Name": "web-01"}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert,
            ):
                _handle_delete(parsed)

        mock_alert.assert_called_once()
        call_kwargs = mock_alert.call_args[1]
        assert call_kwargs["event_type"] == "RESOURCE_DELETED"
        assert call_kwargs["resource_id"] == "i-0abc1234"

    def test_unmonitored_resource_no_lifecycle_alert(self):
        """Monitoring 태그 없고 알람도 없으면 lifecycle 알림 생략."""
        from remediation_handler.lambda_handler import _handle_delete, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0unmonitored",
            resource_type="EC2",
            event_name="TerminateInstances",
            event_category="DELETE",
            change_summary="terminate",
            request_params={},
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]),
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert,
            ):
                _handle_delete(parsed)

        mock_alert.assert_not_called()

    def test_rds_fallback_uses_empty_delete_type(self):
        """KI-008 폴백: delete_type="" 로 delete_alarms 호출."""
        from remediation_handler.lambda_handler import _handle_delete, ParsedEvent

        parsed = ParsedEvent(
            resource_id="my-db",
            resource_type="RDS",
            event_name="DeleteDBInstance",
            event_category="DELETE",
            change_summary="delete",
            request_params={},
            _is_rds_fallback=True,
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]) as mock_del,
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert"),
            ):
                _handle_delete(parsed)

        assert mock_del.call_args[0][1] == ""


# ──────────────────────────────────────────────
# _handle_tag_change — 태그 변경 이벤트 처리
# ──────────────────────────────────────────────

class TestHandleTagChange:
    """TAG_CHANGE 이벤트 처리."""

    def test_monitoring_on_tag_added_creates_alarms(self):
        """Monitoring=on 태그 추가 → create_alarms_for_resource 호출."""
        from remediation_handler.lambda_handler import _handle_tag_change, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0abc1234",
            resource_type="EC2",
            event_name="CreateTags",
            event_category="TAG_CHANGE",
            change_summary="tag add",
            request_params={
                "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]}
            },
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.get_resource_tags",
                      return_value={"Monitoring": "on", "Name": "web-01"}),
                patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                      return_value=["alarm1"]) as mock_create,
            ):
                _handle_tag_change(parsed)

        mock_create.assert_called_once_with("i-0abc1234", "EC2",
                                            {"Monitoring": "on", "Name": "web-01"})

    def test_monitoring_tag_removed_deletes_alarms(self):
        """Monitoring 태그 제거 → delete_alarms + lifecycle 알림."""
        from remediation_handler.lambda_handler import _handle_tag_change, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0abc1234",
            resource_type="EC2",
            event_name="DeleteTags",
            event_category="TAG_CHANGE",
            change_summary="tag delete",
            request_params={
                "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]}
            },
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource",
                      return_value=["alarm1"]) as mock_del,
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert,
            ):
                _handle_tag_change(parsed)

        mock_del.assert_called_once()
        mock_alert.assert_called_once()
        assert mock_alert.call_args[1]["event_type"] == "MONITORING_REMOVED"

    def test_threshold_tag_changed_syncs_alarms(self):
        """Threshold 태그만 변경 + Monitoring=on → sync_alarms_for_resource 호출."""
        from remediation_handler.lambda_handler import _handle_tag_change, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0abc1234",
            resource_type="EC2",
            event_name="CreateTags",
            event_category="TAG_CHANGE",
            change_summary="threshold change",
            request_params={
                "tagSet": {"items": [{"key": "Threshold_CPU", "value": "90"}]}
            },
        )

        tags = {"Monitoring": "on", "Threshold_CPU": "90"}

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value=tags),
                patch("remediation_handler.lambda_handler.sync_alarms_for_resource") as mock_sync,
            ):
                _handle_tag_change(parsed)

        mock_sync.assert_called_once_with("i-0abc1234", "EC2", tags)

    def test_unrelated_tag_change_does_nothing(self):
        """Monitoring/Threshold 관련 없는 태그 변경 → 아무것도 호출 안 함."""
        from remediation_handler.lambda_handler import _handle_tag_change, ParsedEvent

        parsed = ParsedEvent(
            resource_id="i-0abc1234",
            resource_type="EC2",
            event_name="CreateTags",
            event_category="TAG_CHANGE",
            change_summary="unrelated",
            request_params={
                "tagSet": {"items": [{"key": "CostCenter", "value": "123"}]}
            },
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.create_alarms_for_resource") as mock_create,
                patch("remediation_handler.lambda_handler.sync_alarms_for_resource") as mock_sync,
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource") as mock_del,
            ):
                _handle_tag_change(parsed)

        mock_create.assert_not_called()
        mock_sync.assert_not_called()
        mock_del.assert_not_called()


# ──────────────────────────────────────────────
# lambda_handler — 진입점
# ──────────────────────────────────────────────

class TestLambdaHandler:
    """remediation lambda_handler 진입점 검증."""

    def test_valid_delete_event_returns_ok(self):
        """정상 DELETE 이벤트 → ok 반환."""
        from remediation_handler import lambda_handler as lh

        event = _ct_event(
            "TerminateInstances",
            {"instancesSet": {"items": [{"instanceId": "i-0abc1234"}]}},
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]),
                patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}),
                patch("remediation_handler.lambda_handler.send_lifecycle_alert"),
            ):
                result = lh.lambda_handler(event, None)

        assert result["status"] == "ok"

    def test_parse_error_returns_parse_error_status(self):
        """파싱 실패 → parse_error 상태 반환."""
        from remediation_handler import lambda_handler as lh

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with patch("remediation_handler.lambda_handler.send_error_alert"):
                result = lh.lambda_handler({"detail": {}}, None)

        assert result["status"] == "parse_error"

    def test_unsupported_event_returns_parse_error(self):
        """지원하지 않는 이벤트 → parse_error 반환."""
        from remediation_handler import lambda_handler as lh

        event = _ct_event("SomeRandomEvent", {})

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with patch("remediation_handler.lambda_handler.send_error_alert"):
                result = lh.lambda_handler(event, None)

        assert result["status"] == "parse_error"

    def test_tag_change_monitoring_on_returns_ok(self):
        """Monitoring=on 태그 추가 이벤트 → ok 반환."""
        from remediation_handler import lambda_handler as lh

        event = _ct_event(
            "CreateTags",
            {
                "resourcesSet": {"items": [{"resourceId": "i-0abc1234"}]},
                "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]},
            },
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.get_resource_tags",
                      return_value={"Monitoring": "on"}),
                patch("remediation_handler.lambda_handler.create_alarms_for_resource", return_value=[]),
            ):
                result = lh.lambda_handler(event, None)

        assert result["status"] == "ok"

    def test_create_ec2_instance_creates_alarms(self):
        """RunInstances 이벤트 + Monitoring=on → create_alarms_for_resource 호출."""
        from remediation_handler import lambda_handler as lh

        event = _ct_event(
            "RunInstances",
            {},
            {"instancesSet": {"items": [{"instanceId": "i-newinstance"}]}},
        )

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch("remediation_handler.lambda_handler.get_resource_tags",
                      return_value={"Monitoring": "on", "Name": "web-new"}),
                patch("remediation_handler.lambda_handler.create_alarms_for_resource",
                      return_value=["alarm1"]) as mock_create,
            ):
                result = lh.lambda_handler(event, None)

        mock_create.assert_called_once()
        assert result["status"] == "ok"
