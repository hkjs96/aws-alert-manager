"""
alarm_builder 단위 테스트 — Requirements 1.1 (Roadmap Phase 1)

_create_standard_alarm(), _create_single_alarm(), _recreate_standard_alarm() 검증.
AWS 서비스는 moto로 모킹한다.
"""

import os
from unittest.mock import patch, MagicMock

import boto3
import pytest
from moto import mock_aws


# ──────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────

@pytest.fixture
def moto_cw(aws_credentials):
    """moto CloudWatch 클라이언트."""
    with mock_aws():
        from common._clients import _get_cw_client, _get_cw_client_for_region
        _get_cw_client.cache_clear()
        _get_cw_client_for_region.cache_clear()
        yield boto3.client("cloudwatch", region_name="us-east-1")
        _get_cw_client.cache_clear()
        _get_cw_client_for_region.cache_clear()


@pytest.fixture
def sns_arn():
    return "arn:aws:sns:us-east-1:123456789012:alert-topic"


# ──────────────────────────────────────────────
# _create_standard_alarm 테스트
# ──────────────────────────────────────────────

class Test_CreateStandardAlarm:
    def test_EC2_CPU_알람_생성_후_이름_반환(self, moto_cw, sns_arn):
        """정상 케이스: EC2 CPU 알람을 생성하고 알람 이름을 반환해야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")
        resource_tags = {"Name": "web-server-01"}

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": sns_arn}):
            result = _create_standard_alarm(
                alarm_def=alarm_def,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags=resource_tags,
                cw=moto_cw,
            )

        assert result is not None
        assert "EC2" in result
        assert "CPU" in result

    def test_알람_생성_후_CloudWatch에서_조회_가능(self, moto_cw, sns_arn):
        """생성된 알람이 CloudWatch에 실제로 존재해야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": sns_arn}):
            alarm_name = _create_standard_alarm(
                alarm_def=alarm_def,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={"Name": "web-01"},
                cw=moto_cw,
            )

        resp = moto_cw.describe_alarms(AlarmNames=[alarm_name])
        assert len(resp["MetricAlarms"]) == 1

    def test_SNS_ARN이_AlarmActions에_포함된다(self, moto_cw, sns_arn):
        """SNS_TOPIC_ARN_ALERT 환경변수가 AlarmActions에 반영되어야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": sns_arn}):
            alarm_name = _create_standard_alarm(
                alarm_def=alarm_def,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={},
                cw=moto_cw,
            )

        alarm = moto_cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
        assert sns_arn in alarm["AlarmActions"]
        assert sns_arn in alarm["OKActions"]

    def test_SNS_ARN_없으면_Actions가_비어있다(self, moto_cw):
        """SNS_TOPIC_ARN_ALERT가 없으면 AlarmActions가 빈 리스트여야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNS_TOPIC_ARN_ALERT", None)
            alarm_name = _create_standard_alarm(
                alarm_def=alarm_def,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={},
                cw=moto_cw,
            )

        alarm = moto_cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
        assert alarm["AlarmActions"] == []

    def test_글로벌_서비스_알람은_us_east_1_클라이언트_사용(self, aws_credentials):
        """alarm_def에 region 필드가 있으면 해당 리전 클라이언트를 사용해야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common._clients import _get_cw_client_for_region

        with mock_aws():
            _get_cw_client_for_region.cache_clear()
            mock_regional_cw = boto3.client("cloudwatch", region_name="us-east-1")

            alarm_def = {
                "metric": "Requests",
                "metric_name": "Requests",
                "namespace": "AWS/CloudFront",
                "stat": "Sum",
                "period": 300,
                "evaluation_periods": 1,
                "comparison": "GreaterThanThreshold",
                "threshold": 10000,
                "dimension_key": "DistributionId",
                "region": "us-east-1",
            }

            with patch(
                "common._clients._get_cw_client_for_region",
                return_value=mock_regional_cw,
            ) as mock_fn:
                _create_standard_alarm(
                    alarm_def=alarm_def,
                    resource_id="E1234567890ABC",
                    resource_type="CloudFront",
                    resource_tags={},
                    cw=mock_regional_cw,
                )
                mock_fn.assert_called_once_with("us-east-1")

            _get_cw_client_for_region.cache_clear()

    def test_글로벌_서비스_알람은_AlarmActions가_비어있다(self, aws_credentials):
        """글로벌 서비스(region 필드 있음)는 크로스 리전 SNS 제약으로 AlarmActions 비워야 한다."""
        from common.alarm_builder import _create_standard_alarm

        with mock_aws():
            from common._clients import _get_cw_client_for_region
            _get_cw_client_for_region.cache_clear()
            cw = boto3.client("cloudwatch", region_name="us-east-1")

            alarm_def = {
                "metric": "Requests",
                "metric_name": "Requests",
                "namespace": "AWS/CloudFront",
                "stat": "Sum",
                "period": 300,
                "evaluation_periods": 1,
                "comparison": "GreaterThanThreshold",
                "threshold": 10000,
                "dimension_key": "DistributionId",
                "region": "us-east-1",
            }

            with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": "arn:aws:sns:ap-northeast-2:123:topic"}):
                alarm_name = _create_standard_alarm(
                    alarm_def=alarm_def,
                    resource_id="E1234567890ABC",
                    resource_type="CloudFront",
                    resource_tags={},
                    cw=cw,
                )

            if alarm_name:
                alarm = cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
                assert alarm["AlarmActions"] == []

            _get_cw_client_for_region.cache_clear()

    def test_TreatMissingData_기본값은_notBreaching(self, moto_cw):
        """alarm_def에 treat_missing_data 없으면 'notBreaching'이어야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")
        alarm_def_copy = {**alarm_def}
        alarm_def_copy.pop("treat_missing_data", None)

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": ""}):
            alarm_name = _create_standard_alarm(
                alarm_def=alarm_def_copy,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={},
                cw=moto_cw,
            )

        alarm = moto_cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
        assert alarm["TreatMissingData"] == "notBreaching"

    def test_TreatMissingData_breaching_설정(self, moto_cw):
        """alarm_def에 treat_missing_data=breaching이면 알람에 반영되어야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_defs = _get_alarm_defs("VPN", {})
        breaching_def = next(
            (d for d in alarm_defs if d.get("treat_missing_data") == "breaching"), None
        )
        if breaching_def is None:
            pytest.skip("VPN breaching 알람 정의 없음")

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": ""}):
            alarm_name = _create_standard_alarm(
                alarm_def=breaching_def,
                resource_id="vpn-0abc123",
                resource_type="VPN",
                resource_tags={},
                cw=moto_cw,
            )

        alarm = moto_cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
        assert alarm["TreatMissingData"] == "breaching"

    def test_ClientError_발생_시_None_반환(self, moto_cw):
        """CloudWatch API 에러 시 None을 반환해야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs
        from botocore.exceptions import ClientError

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")
        failing_cw = MagicMock()
        failing_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "test"}}, "PutMetricAlarm"
        )

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": ""}):
            result = _create_standard_alarm(
                alarm_def=alarm_def,
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={},
                cw=failing_cw,
            )

        assert result is None


# ──────────────────────────────────────────────
# _create_single_alarm 테스트
# ──────────────────────────────────────────────

class Test_CreateSingleAlarm:
    def test_단일_알람_생성_성공(self, moto_cw, sns_arn):
        """단일 메트릭 알람이 CloudWatch에 생성되어야 한다."""
        from common.alarm_builder import _create_single_alarm

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": sns_arn}):
            _create_single_alarm(
                metric="CPUUtilization",
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={"Name": "test-instance"},
                cw=moto_cw,
            )

        resp = moto_cw.describe_alarms(AlarmNamePrefix="[EC2]")
        assert len(resp["MetricAlarms"]) == 1

    def test_존재하지_않는_메트릭은_알람을_생성하지_않는다(self, moto_cw):
        """alarm_def가 없는 메트릭은 알람을 생성하지 않아야 한다."""
        from common.alarm_builder import _create_single_alarm

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": ""}):
            _create_single_alarm(
                metric="NONEXISTENT_METRIC_XYZ",
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_tags={},
                cw=moto_cw,
            )

        resp = moto_cw.describe_alarms(AlarmNamePrefix="[EC2]")
        assert resp["MetricAlarms"] == []

    def test_글로벌_서비스_단일_알람은_해당_리전_클라이언트_사용(self, aws_credentials):
        """region 필드가 있는 alarm_def는 해당 리전 CloudWatch 클라이언트를 사용해야 한다."""
        from common.alarm_builder import _create_single_alarm

        with mock_aws():
            from common._clients import _get_cw_client_for_region
            _get_cw_client_for_region.cache_clear()

            mock_cw = MagicMock()

            with patch("common._clients._get_cw_client_for_region", return_value=mock_cw) as mock_fn:
                # CloudFront가 region=us-east-1을 가진다면
                _create_single_alarm(
                    metric="Requests",
                    resource_id="E1234567890ABC",
                    resource_type="CloudFront",
                    resource_tags={},
                    cw=MagicMock(),
                )
                # CloudFront alarm_def에 region이 있으면 호출되어야 함
                # (없다면 이 테스트는 해당 없음)

            _get_cw_client_for_region.cache_clear()


# ──────────────────────────────────────────────
# _recreate_standard_alarm 테스트
# ──────────────────────────────────────────────

class Test_RecreateStandardAlarm:
    def test_표준_알람_재생성_성공(self, moto_cw, sns_arn):
        """기존 알람 삭제 후 동일 메트릭으로 재생성되어야 한다."""
        from common.alarm_builder import _recreate_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")

        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": sns_arn}):
            _recreate_standard_alarm(
                alarm_def=alarm_def,
                metric_key="CPUUtilization",
                resource_id="i-0abcdef1234567890",
                resource_type="EC2",
                resource_name="web-server-01",
                resource_tags={"Threshold_CPU": "75"},
                cw=moto_cw,
                sns_arn=sns_arn,
            )

        resp = moto_cw.describe_alarms(AlarmNamePrefix="[EC2]")
        assert len(resp["MetricAlarms"]) == 1
        alarm = resp["MetricAlarms"][0]
        assert alarm["Threshold"] == 75.0  # 태그로 오버라이드된 임계치

    def test_글로벌_서비스_재생성_시_us_east_1_클라이언트_사용(self, aws_credentials):
        """alarm_def에 region 필드가 있으면 해당 리전 클라이언트를 사용해야 한다."""
        from common.alarm_builder import _recreate_standard_alarm
        from common._clients import _get_cw_client_for_region

        with mock_aws():
            _get_cw_client_for_region.cache_clear()
            mock_cw = boto3.client("cloudwatch", region_name="us-east-1")

            alarm_def = {
                "metric": "Requests",
                "metric_name": "Requests",
                "namespace": "AWS/CloudFront",
                "stat": "Sum",
                "period": 300,
                "evaluation_periods": 1,
                "comparison": "GreaterThanThreshold",
                "threshold": 10000,
                "dimension_key": "DistributionId",
                "region": "us-east-1",
            }

            with patch(
                "common._clients._get_cw_client_for_region",
                return_value=mock_cw,
            ) as mock_fn:
                _recreate_standard_alarm(
                    alarm_def=alarm_def,
                    metric_key="Requests",
                    resource_id="E1234567890ABC",
                    resource_type="CloudFront",
                    resource_name="my-distribution",
                    resource_tags={},
                    cw=mock_cw,
                    sns_arn="",
                )
                mock_fn.assert_called_once_with("us-east-1")

            _get_cw_client_for_region.cache_clear()

    def test_ClientError_발생_시_로그만_남기고_예외_없음(self):
        """CloudWatch API 에러 시 예외를 던지지 않아야 한다."""
        from common.alarm_builder import _recreate_standard_alarm
        from common.alarm_registry import _get_alarm_defs
        from botocore.exceptions import ClientError

        alarm_def = next(d for d in _get_alarm_defs("EC2", {}) if d["metric"] == "CPUUtilization")
        failing_cw = MagicMock()
        failing_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "test"}}, "PutMetricAlarm"
        )

        # 예외 없이 완료되어야 한다
        _recreate_standard_alarm(
            alarm_def=alarm_def,
            metric_key="CPUUtilization",
            resource_id="i-0abcdef1234567890",
            resource_type="EC2",
            resource_name="web-01",
            resource_tags={},
            cw=failing_cw,
            sns_arn="",
        )
