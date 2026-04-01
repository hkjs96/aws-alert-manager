"""
통합 테스트 - Daily_Monitor / Remediation_Handler 전체 흐름 검증

Requirements: 1.1, 3.1, 4.1, 5.1, 8.1

패치 경로 원칙:
- sns_notifier 함수는 각 핸들러가 임포트한 위치에서 패치
  (daily_monitor.lambda_handler.send_alert, remediation_handler.lambda_handler.send_lifecycle_alert 등)
- boto3.client는 remediation_handler.lambda_handler.boto3.client 로 패치
- get_resource_tags는 remediation_handler.lambda_handler.get_resource_tags 로 패치
- collector.get_metrics는 common.collectors.{ec2|rds|elb}.get_metrics 로 패치
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch
import pytest

from daily_monitor.lambda_handler import lambda_handler as daily_handler
from remediation_handler.lambda_handler import lambda_handler as remediation_handler


# ──────────────────────────────────────────────
# Daily_Monitor 통합 테스트
# 흐름: 수집 → 메트릭 조회 → 임계치 비교 → 알림 발송
# ──────────────────────────────────────────────

class TestDailyMonitorIntegration:

    def test_full_flow_ec2_threshold_exceeded(self):
        """EC2 CPU 임계치 초과 → SNS 알림 발송 전체 흐름 - Requirements 1.1, 3.1"""
        ec2_resource = {"id": "i-001", "type": "EC2", "tags": {"Monitoring": "on"}, "region": "ap-northeast-2"}

        with patch("common.collectors.ec2.collect_monitored_resources", return_value=[ec2_resource]), \
             patch("common.collectors.rds.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.elb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.docdb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.ec2.get_metrics", return_value={"CPU": 95.0}), \
             patch("common.tag_resolver.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:

            result = daily_handler({}, MagicMock())

        assert result["status"] == "ok"
        assert result["processed"] == 1
        assert result["alerts"] == 1
        mock_alert.assert_called_once_with(
            resource_id="i-001",
            resource_type="EC2",
            metric_name="CPU",
            current_value=95.0,
            threshold=80.0,
            tag_name="",
        )

    def test_full_flow_rds_multiple_metrics(self):
        """RDS CPU + Connections 동시 초과 → 2개 알림 - Requirements 3.3"""
        rds_resource = {"id": "db-prod", "type": "RDS", "tags": {"Monitoring": "on"}, "region": "ap-northeast-2"}

        def mock_threshold(tags, metric_name):
            return {"CPU": 80.0, "Connections": 100.0}.get(metric_name, 80.0)

        with patch("common.collectors.ec2.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.rds.collect_monitored_resources", return_value=[rds_resource]), \
             patch("common.collectors.elb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.docdb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.rds.get_metrics", return_value={"CPU": 90.0, "Connections": 150.0}), \
             patch("common.tag_resolver.get_threshold", side_effect=mock_threshold), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:

            result = daily_handler({}, MagicMock())

        assert result["status"] == "ok"
        assert result["alerts"] == 2
        assert mock_alert.call_count == 2

    def test_full_flow_no_threshold_exceeded_no_alert(self):
        """임계치 미초과 → 알림 없음 - Requirements 3.1"""
        ec2_resource = {"id": "i-002", "type": "EC2", "tags": {"Monitoring": "on"}, "region": "ap-northeast-2"}

        with patch("common.collectors.ec2.collect_monitored_resources", return_value=[ec2_resource]), \
             patch("common.collectors.rds.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.elb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.docdb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.ec2.get_metrics", return_value={"CPU": 50.0}), \
             patch("common.tag_resolver.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:

            result = daily_handler({}, MagicMock())

        assert result["status"] == "ok"
        assert result["alerts"] == 0
        mock_alert.assert_not_called()

    def test_full_flow_metric_none_skipped(self):
        """메트릭 없음(None) → 건너뜀, 알림 없음 - Requirements 3.5"""
        ec2_resource = {"id": "i-003", "type": "EC2", "tags": {"Monitoring": "on"}, "region": "ap-northeast-2"}

        with patch("common.collectors.ec2.collect_monitored_resources", return_value=[ec2_resource]), \
             patch("common.collectors.rds.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.elb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.docdb.collect_monitored_resources", return_value=[]), \
             patch("common.collectors.ec2.get_metrics", return_value=None), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:

            result = daily_handler({}, MagicMock())

        assert result["status"] == "ok"
        assert result["alerts"] == 0
        mock_alert.assert_not_called()

    def test_full_flow_collector_error_continues(self):
        """EC2 수집 오류 → 오류 알림 발송 후 RDS 계속 처리 - Requirements 1.3"""
        rds_resource = {"id": "db-001", "type": "RDS", "tags": {"Monitoring": "on"}, "region": "ap-northeast-2"}

        stack = ExitStack()
        stack.enter_context(
            patch("common.collectors.ec2.collect_monitored_resources",
                  side_effect=Exception("EC2 API error")))
        stack.enter_context(
            patch("common.collectors.rds.collect_monitored_resources",
                  return_value=[rds_resource]))
        for mod in ("elb", "docdb", "elasticache", "natgw", "lambda_fn",
                    "vpn", "apigw", "acm", "backup", "mq", "clb", "opensearch",
                    "sqs", "ecs", "msk", "dynamodb", "cloudfront", "waf",
                    "route53", "dx", "efs", "s3", "sagemaker", "sns"):
            stack.enter_context(
                patch(f"common.collectors.{mod}.collect_monitored_resources",
                      return_value=[]))
        stack.enter_context(
            patch("common.collectors.rds.get_metrics", return_value={"CPU": 50.0}))
        stack.enter_context(
            patch("common.tag_resolver.get_threshold", return_value=80.0))
        mock_err = stack.enter_context(
            patch("daily_monitor.lambda_handler.send_error_alert"))
        stack.enter_context(
            patch("daily_monitor.lambda_handler.send_alert"))

        with stack:
            result = daily_handler({}, MagicMock())

        assert result["status"] == "ok"
        mock_err.assert_called_once()  # EC2 오류 알림
        assert result["processed"] == 1  # RDS는 정상 처리


# ──────────────────────────────────────────────
# Remediation_Handler 통합 테스트
# 흐름: 이벤트 수신 → 파싱 → 태그 확인 → remediation → 알림
# ──────────────────────────────────────────────

class TestRemediationHandlerIntegration:

    def _make_cloudtrail_event(self, event_name: str, resource_id: str, extra_params: dict = None) -> dict:
        params = extra_params or {}
        if event_name in ("ModifyInstanceAttribute", "ModifyInstanceType", "TerminateInstances"):
            params.setdefault("instancesSet", {"items": [{"instanceId": resource_id}]})
        elif event_name in ("ModifyDBInstance", "DeleteDBInstance"):
            params.setdefault("dBInstanceIdentifier", resource_id)
        elif event_name in ("ModifyLoadBalancerAttributes", "ModifyListener", "DeleteLoadBalancer"):
            params.setdefault("loadBalancerArn", resource_id)
        elif event_name in ("CreateTags", "DeleteTags"):
            params.setdefault("resourcesSet", {"items": [{"resourceId": resource_id}]})
        return {"detail": {"eventName": event_name, "requestParameters": params}}

    def test_modify_ec2_with_monitoring_tag_stops_instance(self):
        """EC2 Modify 이벤트 + Monitoring=on → stop_instances 호출 + SNS 알림 - Requirements 4.1, 5.1"""
        event = self._make_cloudtrail_event("ModifyInstanceAttribute", "i-001")
        mock_ec2_client = MagicMock()

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_ec2_client), \
             patch("remediation_handler.lambda_handler.send_remediation_alert") as mock_alert:

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_ec2_client.stop_instances.assert_called_once_with(InstanceIds=["i-001"])
        mock_alert.assert_called_once()
        call_kwargs = mock_alert.call_args.kwargs
        assert call_kwargs["resource_id"] == "i-001"
        assert call_kwargs["action_taken"] == "STOPPED"

    def test_modify_ec2_without_monitoring_tag_skips(self):
        """EC2 Modify 이벤트 + Monitoring 태그 없음 → remediation 미수행 - Requirements 4.2"""
        event = self._make_cloudtrail_event("ModifyInstanceAttribute", "i-002")

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}), \
             patch("remediation_handler.lambda_handler._execute_remediation") as mock_exec, \
             patch("remediation_handler.lambda_handler.send_remediation_alert") as mock_alert:

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_exec.assert_not_called()
        mock_alert.assert_not_called()

    def test_modify_rds_stops_db_instance(self):
        """RDS Modify 이벤트 + Monitoring=on → stop_db_instance 호출 - Requirements 5.1"""
        event = self._make_cloudtrail_event("ModifyDBInstance", "db-prod")
        mock_rds_client = MagicMock()

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_rds_client), \
             patch("remediation_handler.lambda_handler.send_remediation_alert"):

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_rds_client.stop_db_instance.assert_called_once_with(DBInstanceIdentifier="db-prod")

    def test_modify_elb_deletes_load_balancer(self):
        """ELB Modify 이벤트 + Monitoring=on → delete_load_balancer 호출 - Requirements 5.1"""
        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123:loadbalancer/app/my-alb/abc"
        event = self._make_cloudtrail_event("ModifyLoadBalancerAttributes", arn)
        mock_elb_client = MagicMock()

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_elb_client), \
             patch("remediation_handler.lambda_handler.send_remediation_alert"):

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_elb_client.delete_load_balancer.assert_called_once_with(LoadBalancerArn=arn)

    def test_delete_ec2_with_monitoring_tag_sends_lifecycle_alert(self):
        """EC2 삭제 이벤트 + Monitoring=on → lifecycle SNS 알림 - Requirements 8.1, 8.2"""
        event = self._make_cloudtrail_event("TerminateInstances", "i-003")

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]):

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "RESOURCE_DELETED"

    def test_delete_ec2_without_monitoring_tag_no_alert(self):
        """EC2 삭제 이벤트 + Monitoring 태그 없음 + 알람 없음 → 알림 없음 - Requirements 8.3"""
        event = self._make_cloudtrail_event("TerminateInstances", "i-004")

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={}), \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]), \
             patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert:

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()

    def test_delete_tags_monitoring_sends_monitoring_removed_alert(self):
        """DeleteTags Monitoring 제거 → MONITORING_REMOVED 알림 - Requirements 8.5"""
        event = {
            "detail": {
                "eventName": "DeleteTags",
                "requestParameters": {
                    "resourcesSet": {"items": [{"resourceId": "i-005"}]},
                    "tagSet": {"items": [{"key": "Monitoring"}]},
                },
            }
        }

        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.delete_alarms_for_resource", return_value=[]):
            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_called_once()
        assert mock_alert.call_args.kwargs["event_type"] == "MONITORING_REMOVED"

    def test_create_tags_monitoring_on_no_sns_alert(self):
        """CreateTags Monitoring=on 추가 → SNS 알림 없음 (로그만) - Requirements 8.6"""
        event = {
            "detail": {
                "eventName": "CreateTags",
                "requestParameters": {
                    "resourcesSet": {"items": [{"resourceId": "i-006"}]},
                    "tagSet": {"items": [{"key": "Monitoring", "value": "on"}]},
                },
            }
        }

        with patch("remediation_handler.lambda_handler.send_lifecycle_alert") as mock_alert, \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err, \
             patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.create_alarms_for_resource", return_value=[]):

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "ok"
        mock_alert.assert_not_called()
        mock_err.assert_not_called()

    def test_invalid_event_returns_parse_error(self):
        """잘못된 이벤트 → parse_error 반환 + SNS 오류 알림 - Requirements 4.4"""
        with patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:
            result = remediation_handler({"detail": {}}, MagicMock())

        assert result["status"] == "parse_error"
        mock_err.assert_called_once()

    def test_remediation_failure_returns_error_and_sends_alert(self):
        """Remediation AWS API 실패 → error 반환 + SNS 오류 알림 - Requirements 5.3"""
        event = self._make_cloudtrail_event("ModifyInstanceAttribute", "i-007")
        mock_ec2_client = MagicMock()
        mock_ec2_client.stop_instances.side_effect = Exception("InsufficientInstanceCapacity")

        with patch("remediation_handler.lambda_handler.get_resource_tags", return_value={"Monitoring": "on"}), \
             patch("remediation_handler.lambda_handler.boto3.client", return_value=mock_ec2_client), \
             patch("remediation_handler.lambda_handler.send_error_alert") as mock_err:

            result = remediation_handler(event, MagicMock())

        assert result["status"] == "error"
        mock_err.assert_called_once()
