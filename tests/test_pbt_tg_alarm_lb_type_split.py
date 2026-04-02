"""
Property-Based Tests: TG Alarm LB Type Split

Property 1: Bug Condition — NLB TG에 ALB 전용 알람 생성 버그
Property 2: Preservation — ALB TG 및 비-TG 리소스 알람 동작 유지

**Validates: Requirements 1.1, 1.2, 2.1, 2.4, 3.1, 3.2, 3.3**
"""

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from common.alarm_manager import (
    _get_alarm_defs,
    _get_cw_client,
    _parse_alarm_metadata,
    create_alarms_for_resource,
)


# ──────────────────────────────────────────────
# Hypothesis 전략: NLB TG ARN + NLB ARN 조합
# ──────────────────────────────────────────────

# TG 이름: 영소문자+숫자+하이픈, 2~32자
_tg_names = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)

# NLB 이름: 영소문자+숫자+하이픈, 2~32자
_nlb_names = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)


# ──────────────────────────────────────────────
# 환경 설정
# ──────────────────────────────────────────────

_ENV = {
    "ENVIRONMENT": "test",
    "AWS_DEFAULT_REGION": "us-east-1",
}


def _setup_sns_topic() -> str:
    """moto mock SNS 토픽 생성 후 ARN 반환."""
    sns = boto3.client("sns", region_name="us-east-1")
    resp = sns.create_topic(Name="test-alert")
    return resp["TopicArn"]


def _extract_alarm_metric_keys(resource_id: str) -> set[str]:
    """CloudWatch에서 resource_id에 해당하는 알람들의 metric_key 집합 추출.

    AlarmDescription의 JSON 메타데이터에서 metric_key를 파싱한다.
    """
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    paginator = cw.get_paginator("describe_alarms")
    metric_keys: set[str] = set()

    for page in paginator.paginate(AlarmNamePrefix="[TG]"):
        for alarm in page.get("MetricAlarms", []):
            metadata = _parse_alarm_metadata(alarm.get("AlarmDescription", ""))
            if metadata and metadata.get("resource_id") == resource_id:
                metric_keys.add(metadata["metric_key"])

    return metric_keys


# ──────────────────────────────────────────────
# Bug Condition Exploration Test
# ──────────────────────────────────────────────

class TestNLBTGAlarmLBTypeSplit:
    """
    NLB TG에 ALB 전용 메트릭(RequestCountPerTarget, TGResponseTime)
    알람이 생성되지 않아야 하는지 검증.

    수정 전 코드에서 FAIL 예상 — 버그 존재 증명.

    **Validates: Requirements 1.1, 1.2, 2.1, 2.4**
    """

    @given(tg_name=_tg_names, nlb_name=_nlb_names)
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_nlb_tg_should_not_have_alb_only_alarms(self, tg_name, nlb_name):
        """
        **Property 1: Bug Condition** — NLB TG에 ALB 전용 알람 미생성

        NLB TG에 대해 create_alarms_for_resource() 호출 시
        RequestCountPerTarget과 TGResponseTime 알람이 생성되지 않아야 한다.

        수정 전 코드에서 FAIL 예상:
        - _get_alarm_defs("TG")가 _lb_type을 무시하고 4개 알람 정의를 반환
        - RequestCountPerTarget과 TGResponseTime이 NLB TG에도 생성됨

        **Validates: Requirements 1.1, 1.2, 2.1, 2.4**
        """
        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            sns_arn = _setup_sns_topic()
            mp.setenv("SNS_TOPIC_ARN_ALERT", sns_arn)

            # NLB TG ARN 구성
            tg_arn = (
                f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
                f":targetgroup/{tg_name}/1234567890abcdef"
            )
            nlb_arn = (
                f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
                f":loadbalancer/net/{nlb_name}/1234567890abcdef"
            )

            resource_tags = {
                "_lb_type": "network",
                "_lb_arn": nlb_arn,
                "Monitoring": "on",
                "Name": tg_name,
            }

            # 알람 생성
            created = create_alarms_for_resource(tg_arn, "TG", resource_tags)

            # 생성된 알람에서 metric_key 추출
            alarm_metrics = _extract_alarm_metric_keys(tg_arn)

        # NLB TG 공통 메트릭은 반드시 존재
        assert "HealthyHostCount" in alarm_metrics, (
            f"HealthyHostCount alarm missing for NLB TG. "
            f"Created alarms: {created}, metric_keys: {alarm_metrics}"
        )
        assert "UnHealthyHostCount" in alarm_metrics, (
            f"UnHealthyHostCount alarm missing for NLB TG. "
            f"Created alarms: {created}, metric_keys: {alarm_metrics}"
        )

        # ALB 전용 메트릭은 NLB TG에 생성되면 안 됨
        # 수정 전 코드에서 FAIL 예상 — 4개 모두 생성됨
        assert "RequestCountPerTarget" not in alarm_metrics, (
            f"RequestCountPerTarget alarm should NOT be created for NLB TG. "
            f"This is an ALB-only metric that causes INSUFFICIENT_DATA on NLB. "
            f"Created alarms: {created}, metric_keys: {alarm_metrics}"
        )
        assert "TGResponseTime" not in alarm_metrics, (
            f"TGResponseTime alarm should NOT be created for NLB TG. "
            f"This is an ALB-only metric that causes INSUFFICIENT_DATA on NLB. "
            f"Created alarms: {created}, metric_keys: {alarm_metrics}"
        )


# ──────────────────────────────────────────────
# Hypothesis 전략: ALB TG ARN + ALB ARN 조합
# ──────────────────────────────────────────────

_alb_names = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)


# ──────────────────────────────────────────────
# 비-TG 리소스 유형별 기대 알람 메트릭 키
# ──────────────────────────────────────────────

_EXPECTED_NON_TG_METRICS: dict[str, tuple[int, set[str]]] = {
    "EC2": (4, {"CPU", "Memory", "Disk", "StatusCheckFailed"}),
    "RDS": (7, {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency", "ConnectionAttempts"}),
    "ALB": (5, {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}),
    "NLB": (5, {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}),
}

_ALB_TG_EXPECTED_METRICS = {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}


# ──────────────────────────────────────────────
# Property 2: Preservation Tests
# ──────────────────────────────────────────────

class TestPreservationALBTG:
    """
    ALB TG(`_lb_type="application"`)에 대해 create_alarms_for_resource() 호출 시
    기존과 동일하게 4개 알람이 생성되는지 검증.

    수정 전 코드에서 PASS 예상 — 기존 동작 기준선 확인.

    **Validates: Requirements 3.1**
    """

    @given(tg_name=_tg_names, alb_name=_alb_names)
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_alb_tg_creates_four_alarms(self, tg_name, alb_name):
        """
        **Property 2a: Preservation** — ALB TG 4개 알람 생성 유지

        ALB TG(`_lb_type="application"`)에 대해 create_alarms_for_resource() 호출 시
        HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime
        4개 알람이 모두 생성되어야 한다.

        **Validates: Requirements 3.1**
        """
        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            sns_arn = _setup_sns_topic()
            mp.setenv("SNS_TOPIC_ARN_ALERT", sns_arn)

            # ALB TG ARN 구성
            tg_arn = (
                f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
                f":targetgroup/{tg_name}/1234567890abcdef"
            )
            alb_arn = (
                f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
                f":loadbalancer/app/{alb_name}/1234567890abcdef"
            )

            resource_tags = {
                "_lb_type": "application",
                "_lb_arn": alb_arn,
                "Monitoring": "on",
                "Name": tg_name,
            }

            # 알람 생성
            created = create_alarms_for_resource(tg_arn, "TG", resource_tags)

            # 생성된 알람에서 metric_key 추출
            alarm_metrics = _extract_alarm_metric_keys(tg_arn)

        # ALB TG는 4개 알람 모두 생성되어야 함
        assert len(alarm_metrics) == 4, (
            f"ALB TG should create exactly 4 alarms. "
            f"Created: {created}, metric_keys: {alarm_metrics}"
        )
        assert alarm_metrics == _ALB_TG_EXPECTED_METRICS, (
            f"ALB TG alarm metrics mismatch. "
            f"Expected: {_ALB_TG_EXPECTED_METRICS}, Got: {alarm_metrics}"
        )


class TestPreservationNonTGResources:
    """
    비-TG 리소스(EC2, RDS, ALB, NLB)에 대해 _get_alarm_defs() 반환값이
    기존과 동일한지 검증.

    수정 전 코드에서 PASS 예상 — 기존 동작 기준선 확인.

    **Validates: Requirements 3.3**
    """

    # 비-TG 리소스 유형 전략
    _non_tg_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB"])

    @given(resource_type=_non_tg_types)
    @settings(max_examples=20, deadline=None)
    def test_non_tg_alarm_defs_unchanged(self, resource_type):
        """
        **Property 2b: Preservation** — 비-TG 리소스 알람 정의 유지

        EC2, RDS, ALB, NLB에 대해 _get_alarm_defs() 반환값이
        기대하는 알람 개수 및 메트릭 키 집합과 동일해야 한다.

        **Validates: Requirements 3.3**
        """
        alarm_defs = _get_alarm_defs(resource_type)
        expected_count, expected_metrics = _EXPECTED_NON_TG_METRICS[resource_type]

        actual_metrics = {d["metric"] for d in alarm_defs}

        assert len(alarm_defs) == expected_count, (
            f"{resource_type}: expected {expected_count} alarm defs, "
            f"got {len(alarm_defs)}. Metrics: {actual_metrics}"
        )
        assert actual_metrics == expected_metrics, (
            f"{resource_type}: alarm metric keys mismatch. "
            f"Expected: {expected_metrics}, Got: {actual_metrics}"
        )
