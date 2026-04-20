"""
알람 검색 테스트

_find_alarms_for_resource() 레거시+새 포맷 호환 검색, 리소스 타입별 접두사 검색 검증.
"""

from unittest.mock import MagicMock, patch

import boto3 as _boto3
import pytest
from moto import mock_aws

from common.alarm_manager import (
    _find_alarms_for_resource,
    delete_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    from common._clients import _get_cw_client
    _get_cw_client.cache_clear()
    yield
    _get_cw_client.cache_clear()


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")


# ──────────────────────────────────────────────
# delete_alarms_for_resource / _find_alarms tests
# ──────────────────────────────────────────────

class TestDeleteAlarms:

    def test_find_alarms_deduplicates_legacy_and_new_format(self):
        """레거시와 새 포맷 검색 결과가 중복되지 않는지 확인."""
        mock_cw = MagicMock()
        shared_alarm = {"AlarmName": "i-001-CPU-prod"}
        new_alarm = {"AlarmName": "[EC2] srv CPUUtilization > 80% (TagName: i-001)"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": [shared_alarm]}],
            [{"MetricAlarms": [shared_alarm, new_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        assert result.count("i-001-CPU-prod") == 1
        assert "[EC2] srv CPUUtilization > 80% (TagName: i-001)" in result
        assert len(result) == 2

    def test_ec2_deletes_legacy_and_new_format(self):
        mock_cw = MagicMock()
        legacy_page = {"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
            {"AlarmName": "i-001-Memory-prod"},
        ]}
        new_page = {"MetricAlarms": [
            {"AlarmName": "[EC2] my-server CPUUtilization > 80% (TagName: i-001)"},
            {"AlarmName": "[EC2] my-server mem_used_percent > 80% (TagName: i-001)"},
        ]}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [[legacy_page], [new_page]]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert len(deleted) == 4
        mock_cw.delete_alarms.assert_called_once()

    def test_no_alarms_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("x-001", "UNKNOWN")
        assert deleted == []

    def test_client_error_returns_empty(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.delete_alarms.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFound", "Message": "nope"}}, "DeleteAlarms"
        )
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert deleted == []

    def test_find_alarms_alb_also_searches_elb_prefix(self):
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        legacy_alarm = {"AlarmName": f"[ELB] my-alb RequestCount > 5000 (TagName: {alb_arn})"}
        new_alarm = {"AlarmName": f"[ALB] my-alb RequestCount > 5000 (TagName: {alb_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],
            [{"MetricAlarms": [new_alarm]}],
            [{"MetricAlarms": [legacy_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert new_alarm["AlarmName"] in result
        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 2

    def test_find_alarms_nlb_also_searches_elb_prefix(self):
        mock_cw = MagicMock()
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        legacy_alarm = {"AlarmName": f"[ELB] my-nlb ProcessedBytes > 1000 (TagName: {nlb_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],
            [{"MetricAlarms": []}],
            [{"MetricAlarms": [legacy_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(nlb_arn, "NLB")

        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 1

    def test_find_alarms_tg_also_searches_elb_prefix(self):
        """Validates: Requirements 2.4, 3.5"""
        mock_cw = MagicMock()
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        legacy_alarm = {"AlarmName": f"[ELB] my-tg HealthyHostCount < 1 (TagName: {tg_arn})"}
        new_alarm = {"AlarmName": f"[TG] my-tg HealthyHostCount < 1 (TagName: {tg_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],
            [{"MetricAlarms": [new_alarm]}],
            [{"MetricAlarms": [legacy_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(tg_arn, "TG")

        assert new_alarm["AlarmName"] in result
        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 2

    def test_find_alarms_ec2_does_not_search_elb_prefix(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],
            [{"MetricAlarms": []}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        assert result == []
        assert mock_paginator.paginate.call_count == 2


# ──────────────────────────────────────────────
# _find_alarms_for_resource() moto 기반 테스트
# ──────────────────────────────────────────────

def _put_alarm(cw, alarm_name: str) -> None:
    """moto CloudWatch에 더미 알람 생성 헬퍼."""
    cw.put_metric_alarm(
        AlarmName=alarm_name,
        Namespace="AWS/ApplicationELB",
        MetricName="RequestCount",
        Dimensions=[{"Name": "LoadBalancer", "Value": "app/my-alb/abc"}],
        Statistic="Sum",
        Period=60,
        EvaluationPeriods=1,
        Threshold=100,
        ComparisonOperator="GreaterThanThreshold",
    )


class TestFindAlarmsForResourceMoto:
    """_find_alarms_for_resource() 레거시+새 포맷 호환 검색 테스트 (moto 기반).
    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """

    @mock_aws
    def test_finds_short_id_suffix_alarms_only(self):
        """Validates: Requirements 3.1"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123def456"
        short_id = "my-alb/abc123def456"

        _put_alarm(cw, f"[ALB] my-alb RequestCount > 100 (TagName: {short_id})")
        _put_alarm(cw, f"[ALB] my-alb HTTPCode_ELB_5XX_Count > 50 (TagName: {short_id})")

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert len(result) == 2
        assert all(name.endswith(f"(TagName: {short_id})") for name in result)

    @mock_aws
    def test_finds_legacy_full_arn_suffix_alarms_only(self):
        """Validates: Requirements 3.2"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123def456"

        _put_alarm(cw, f"[ALB] my-alb RequestCount > 100 (TagName: {alb_arn})")
        _put_alarm(cw, f"[ALB] my-alb HTTPCode_ELB_5XX_Count > 50 (TagName: {alb_arn})")

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert len(result) == 2
        assert all(name.endswith(f"(TagName: {alb_arn})") for name in result)

    @mock_aws
    def test_finds_mixed_short_id_and_full_arn_no_duplicates(self):
        """Validates: Requirements 3.3"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123def456"
        short_id = "my-tg/abc123def456"

        _put_alarm(cw, f"[TG] my-tg HealthyHostCount < 2 (TagName: {tg_arn})")
        _put_alarm(cw, f"[TG] my-tg UnHealthyHostCount > 0 (TagName: {short_id})")

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(tg_arn, "TG")

        assert len(result) == 2
        assert len(set(result)) == 2
        names_str = " ".join(result)
        assert "HealthyHostCount" in names_str
        assert "UnHealthyHostCount" in names_str

    @mock_aws
    def test_ec2_search_unchanged(self):
        """Validates: Requirements 3.4"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        instance_id = "i-0abc123def456789a"

        cw.put_metric_alarm(
            AlarmName=f"{instance_id}-CPU-prod",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )
        cw.put_metric_alarm(
            AlarmName=f"[EC2] my-server CPUUtilization > 80% (TagName: {instance_id})",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(instance_id, "EC2")

        assert len(result) == 2
        assert f"{instance_id}-CPU-prod" in result
        assert f"[EC2] my-server CPUUtilization > 80% (TagName: {instance_id})" in result

    @mock_aws
    def test_rds_search_unchanged(self):
        """Validates: Requirements 3.4"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-database"

        cw.put_metric_alarm(
            AlarmName=f"[RDS] my-db CPUUtilization > 80% (TagName: {db_id})",
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id, "RDS")

        assert len(result) == 1
        assert f"[RDS] my-db CPUUtilization > 80% (TagName: {db_id})" in result


# ──────────────────────────────────────────────
# _find_alarms_for_resource() AuroraRDS 검색 검증
# ──────────────────────────────────────────────

class TestFindAlarmsForResourceAuroraRDS:
    """Validates: Requirements 8.1, 8.2"""

    @mock_aws
    def test_aurora_rds_explicit_type_searches_with_correct_prefix_and_suffix(self):
        """Validates: Requirements 8.1"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-aurora-instance"

        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})",
            Namespace="AWS/RDS", MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average", Period=300, EvaluationPeriods=1,
            Threshold=80, ComparisonOperator="GreaterThanThreshold",
        )
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora FreeLocalStorage < 10GB (TagName: {db_id})",
            Namespace="AWS/RDS", MetricName="FreeLocalStorage",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average", Period=300, EvaluationPeriods=1,
            Threshold=10737418240, ComparisonOperator="LessThanThreshold",
        )
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] other-aurora CPUUtilization > 80% (TagName: other-instance)",
            Namespace="AWS/RDS", MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": "other-instance"}],
            Statistic="Average", Period=300, EvaluationPeriods=1,
            Threshold=80, ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id, "AuroraRDS")

        assert len(result) == 2
        assert all(name.endswith(f"(TagName: {db_id})") for name in result)
        assert all(name.startswith("[AuroraRDS] ") for name in result)

    @mock_aws
    def test_default_fallback_includes_aurora_rds(self):
        """Validates: Requirements 8.2"""
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-aurora-db"

        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})",
            Namespace="AWS/RDS", MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average", Period=300, EvaluationPeriods=1,
            Threshold=80, ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common._clients._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id)

        assert len(result) >= 1
        assert f"[AuroraRDS] my-aurora CPUUtilization > 80% (TagName: {db_id})" in result


# ──────────────────────────────────────────────
# 신규 리소스 타입 접두사 검색 검증
# ──────────────────────────────────────────────

class TestAlarmSearchNewTypes:
    """Validates: Requirements 12.2"""

    _NEW_TYPES = [
        "Lambda", "VPN", "APIGW", "ACM",
        "Backup", "MQ", "CLB", "OpenSearch",
    ]

    def test_default_fallback_includes_new_types(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("some-resource", cw=mock_cw)

        prefixes = []
        for call in mock_paginator.paginate.call_args_list:
            prefix = call.kwargs.get("AlarmNamePrefix", "")
            prefixes.append(prefix)

        for rt in self._NEW_TYPES:
            assert f"[{rt}] " in prefixes, f"[{rt}] prefix not searched in default fallback"

    def test_specific_type_searches_correct_prefix(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("my-func", "Lambda", cw=mock_cw)

        prefixes = [
            call.kwargs.get("AlarmNamePrefix", "")
            for call in mock_paginator.paginate.call_args_list
        ]
        assert "[Lambda] " in prefixes

    @pytest.mark.parametrize("resource_type", _NEW_TYPES)
    def test_each_new_type_searches_with_correct_prefix(self, resource_type):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("res-001", resource_type, cw=mock_cw)

        prefixes = [
            call.kwargs.get("AlarmNamePrefix", "")
            for call in mock_paginator.paginate.call_args_list
        ]
        assert f"[{resource_type}] " in prefixes, f"[{resource_type}] prefix not searched"


# ──────────────────────────────────────────────
# 확장 리소스 타입 접두사 검색 검증 (12개 신규)
# ──────────────────────────────────────────────

class TestAlarmSearchExtendedTypes:
    """Validates: Requirements 16.2"""

    _EXTENDED_TYPES = [
        "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
        "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
    ]

    def test_default_fallback_includes_extended_types(self):
        """resource_type 미지정 시 기본 폴백 목록에 12개 신규 타입 포함 검증."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("some-resource", cw=mock_cw)

        prefixes = []
        for call in mock_paginator.paginate.call_args_list:
            prefix = call.kwargs.get("AlarmNamePrefix", "")
            prefixes.append(prefix)

        for rt in self._EXTENDED_TYPES:
            assert f"[{rt}] " in prefixes, f"[{rt}] prefix not searched in default fallback"

    def test_sqs_specific_type_searches_correct_prefix(self):
        """SQS resource_type 지정 시 [SQS] 접두사 검색 검증."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("my-queue", "SQS", cw=mock_cw)

        prefixes = [
            call.kwargs.get("AlarmNamePrefix", "")
            for call in mock_paginator.paginate.call_args_list
        ]
        assert "[SQS] " in prefixes

    @pytest.mark.parametrize("resource_type", _EXTENDED_TYPES)
    def test_each_extended_type_searches_with_correct_prefix(self, resource_type):
        """12개 신규 타입 각각에 대해 [{type}] 접두사 검색 검증."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        _find_alarms_for_resource("res-001", resource_type, cw=mock_cw)

        prefixes = [
            call.kwargs.get("AlarmNamePrefix", "")
            for call in mock_paginator.paginate.call_args_list
        ]
        assert f"[{resource_type}] " in prefixes, f"[{resource_type}] prefix not searched"
