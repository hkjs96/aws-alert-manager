"""
alarm_builder PBT — Requirements 1.1 (Roadmap Phase 1)

Property 1: 생성된 알람 이름이 255자 이하
Property 2: AlarmActions가 알람 리전과 동일한 리전의 SNS ARN만 포함
Property 3: 글로벌 서비스(region 필드 있음) 알람은 AlarmActions가 비어있음
"""

import os
from unittest.mock import patch, MagicMock

import boto3
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from moto import mock_aws


# ──────────────────────────────────────────────
# 전략 (Strategies)
# ──────────────────────────────────────────────

resource_types = st.sampled_from([
    "EC2", "RDS", "ALB", "NLB", "TG", "VPN", "ECS", "SQS", "EFS",
])

resource_ids = st.one_of(
    st.from_regex(r"i-[0-9a-f]{8,17}", fullmatch=True),    # EC2
    st.from_regex(r"db-[a-z0-9\-]{5,15}", fullmatch=True), # RDS
    st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"
    )),
)

resource_names = st.one_of(
    st.just(""),
    st.text(min_size=1, max_size=100, alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"
    )),
)

thresholds = st.one_of(
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=0, max_value=1000000).map(float),
)


# ──────────────────────────────────────────────
# Property 1: 알람 이름이 255자 이하
# ──────────────────────────────────────────────

class TestAlarmNameLength:
    @given(
        resource_type=resource_types,
        resource_id=resource_ids,
        resource_name=resource_names,
        threshold=thresholds,
        metric=st.sampled_from(["CPU", "Memory", "Disk-root", "FreeMemoryGB", "CPU"]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_알람_이름이_255자를_초과하지_않는다(
        self, resource_type, resource_id, resource_name, threshold, metric
    ):
        """어떤 입력 조합에서도 알람 이름은 반드시 255자 이하여야 한다."""
        from common.alarm_naming import _pretty_alarm_name

        name = _pretty_alarm_name(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            metric=metric,
            threshold=threshold,
        )

        assert len(name) <= 255, (
            f"알람 이름 {len(name)}자 초과: {name!r}"
        )

    @given(
        long_label=st.text(min_size=200, max_size=300, alphabet="abcdefghijklmnopqrstuvwxyz-"),
        threshold=thresholds,
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_긴_label_truncate_후에도_255자_이하(self, long_label, threshold):
        """매우 긴 label도 truncate 후 255자 이하여야 한다."""
        from common.alarm_naming import _pretty_alarm_name

        name = _pretty_alarm_name(
            resource_type="EC2",
            resource_id="i-0abcdef1234567890",
            resource_name=long_label,
            metric="CPU",
            threshold=threshold,
        )

        assert len(name) <= 255


# ──────────────────────────────────────────────
# Property 2: AlarmActions가 알람 리전과 동일 리전 SNS ARN만 포함
# ──────────────────────────────────────────────

class TestAlarmActionsRegion:
    @given(
        region=st.sampled_from(["us-east-1", "ap-northeast-2", "eu-west-1"]),
        metric=st.sampled_from(["CPU", "Memory"]),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_AlarmActions_SNS가_알람_리전과_동일해야_한다(self, region, metric):
        """AlarmActions에 포함된 SNS ARN의 리전이 알람 리전과 일치해야 한다."""
        from common.alarm_builder import _create_standard_alarm
        from common.alarm_registry import _get_alarm_defs

        alarm_def = next(
            (d for d in _get_alarm_defs("EC2", {}) if d["metric"] == metric),
            None,
        )
        if alarm_def is None:
            return  # 해당 metric 없으면 스킵

        sns_arn = f"arn:aws:sns:{region}:123456789012:alert-topic"

        with mock_aws():
            from common._clients import _get_cw_client
            _get_cw_client.cache_clear()
            cw = boto3.client("cloudwatch", region_name=region)

            with patch.dict(os.environ, {
                "SNS_TOPIC_ARN_ALERT": sns_arn,
                "AWS_DEFAULT_REGION": region,
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
            }):
                alarm_name = _create_standard_alarm(
                    alarm_def=alarm_def,
                    resource_id="i-0abcdef1234567890",
                    resource_type="EC2",
                    resource_tags={},
                    cw=cw,
                )

            if alarm_name:
                alarm = cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
                for action_arn in alarm.get("AlarmActions", []):
                    arn_parts = action_arn.split(":")
                    if len(arn_parts) >= 5:
                        action_region = arn_parts[3]
                        assert action_region == region, (
                            f"AlarmAction 리전({action_region})이 알람 리전({region})과 불일치"
                        )

            _get_cw_client.cache_clear()


# ──────────────────────────────────────────────
# Property 3: 글로벌 서비스 알람은 AlarmActions가 비어있음
# ──────────────────────────────────────────────

class TestGlobalServiceAlarmActions:
    @given(
        resource_id=st.from_regex(r"[A-Z0-9]{10,14}", fullmatch=True),
        sns_arn=st.just("arn:aws:sns:ap-northeast-2:123456789012:alert-topic"),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_글로벌_서비스_AlarmActions가_비어있어야_한다(
        self, resource_id, sns_arn
    ):
        """region 필드가 있는 alarm_def는 AlarmActions가 항상 비어야 한다 (크로스 리전 SNS 제약)."""
        from common.alarm_builder import _create_standard_alarm

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

        with mock_aws():
            from common._clients import _get_cw_client_for_region
            _get_cw_client_for_region.cache_clear()
            cw = boto3.client("cloudwatch", region_name="us-east-1")

            with patch.dict(os.environ, {
                "SNS_TOPIC_ARN_ALERT": sns_arn,
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
            }):
                with patch("common._clients._get_cw_client_for_region", return_value=cw):
                    alarm_name = _create_standard_alarm(
                        alarm_def=alarm_def,
                        resource_id=resource_id,
                        resource_type="CloudFront",
                        resource_tags={},
                        cw=cw,
                    )

            if alarm_name:
                alarm = cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"][0]
                assert alarm["AlarmActions"] == [], (
                    f"글로벌 서비스 알람에 AlarmActions가 있어서는 안 됨: {alarm['AlarmActions']}"
                )

            _get_cw_client_for_region.cache_clear()
