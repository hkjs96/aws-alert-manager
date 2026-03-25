"""
Preservation Property Test - 기존 하드코딩 메트릭 알람 생성 보존

Property 2 (Preservation): 하드코딩 목록에 있는 메트릭만 포함하는 태그 조합에 대해
create_alarms_for_resource()가 기존과 동일한 알람 개수, 이름 포맷, 네임스페이스,
디멘션, 임계치로 알람을 생성하는지 검증.

**Validates: Requirements 3.1, 3.2, 3.6, 3.7, 3.8**

EXPECTED: These tests PASS on unfixed code (existing behavior is correct).
"""

import os
import re

import boto3
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from moto import mock_aws

from common.alarm_manager import (
    _get_cw_client,
    _shorten_elb_resource_id,
    create_alarms_for_resource,
)

# ──────────────────────────────────────────────
# 하드코딩 메트릭 정의 (alarm_manager.py 기준)
# ──────────────────────────────────────────────

_HARDCODED_METRICS = {
    "EC2": ["CPU", "Memory", "Disk", "StatusCheckFailed"],
    "RDS": [
        "CPU", "FreeMemoryGB", "FreeStorageGB",
        "Connections", "ReadLatency", "WriteLatency",
    ],
    "ALB": ["RequestCount", "ELB5XX", "TargetResponseTime"],
    "NLB": [
        "ProcessedBytes", "ActiveFlowCount", "NewFlowCount",
        "TCPClientReset", "TCPTargetReset",
    ],
    "TG": [
        "HealthyHostCount", "UnHealthyHostCount",
        "RequestCountPerTarget", "TGResponseTime",
    ],
}

# 알람 개수 기대값 (Disk는 CWAgent 메트릭 등록 시 1개)
_EXPECTED_ALARM_COUNTS = {
    "EC2": 4,  # CPU + Memory + Disk(/) + StatusCheckFailed
    "RDS": 6,  # CPU + FreeMemoryGB + FreeStorageGB + Connections + ReadLatency + WriteLatency
    "ALB": 3,  # RequestCount + ELB5XX + TargetResponseTime
    "NLB": 5,  # ProcessedBytes + ActiveFlowCount + NewFlowCount + TCPClientReset + TCPTargetReset
    "TG": 4,   # RequestCount + HealthyHostCount + RequestCountPerTarget + TGResponseTime
}

# 메트릭별 네임스페이스 매핑
_METRIC_NAMESPACE = {
    "EC2": {
        "CPU": "AWS/EC2",
        "Memory": "CWAgent",
        "Disk": "CWAgent",
        "StatusCheckFailed": "AWS/EC2",
    },
    "RDS": {
        "CPU": "AWS/RDS",
        "FreeMemoryGB": "AWS/RDS",
        "FreeStorageGB": "AWS/RDS",
        "Connections": "AWS/RDS",
        "ReadLatency": "AWS/RDS",
        "WriteLatency": "AWS/RDS",
    },
    "ALB": {
        "RequestCount": "AWS/ApplicationELB",
        "ELB5XX": "AWS/ApplicationELB",
        "TargetResponseTime": "AWS/ApplicationELB",
    },
    "NLB": {
        "ProcessedBytes": "AWS/NetworkELB",
        "ActiveFlowCount": "AWS/NetworkELB",
        "NewFlowCount": "AWS/NetworkELB",
        "TCPClientReset": "AWS/NetworkELB",
        "TCPTargetReset": "AWS/NetworkELB",
    },
    "TG": {
        "HealthyHostCount": "AWS/ApplicationELB",
        "UnHealthyHostCount": "AWS/ApplicationELB",
        "RequestCountPerTarget": "AWS/ApplicationELB",
        "TGResponseTime": "AWS/ApplicationELB",
    },
}

# 메트릭별 display name 매핑
_METRIC_DISPLAY = {
    "CPU": "CPUUtilization",
    "Memory": "mem_used_percent",
    "Disk": "disk_used_percent",
    "FreeMemoryGB": "FreeableMemory",
    "FreeStorageGB": "FreeStorageSpace",
    "Connections": "DatabaseConnections",
    "RequestCount": "RequestCount",
    "HealthyHostCount": "HealthyHostCount",
    "UnHealthyHostCount": "UnHealthyHostCount",
    "ProcessedBytes": "ProcessedBytes",
    "ActiveFlowCount": "ActiveFlowCount",
    "NewFlowCount": "NewFlowCount",
    "StatusCheckFailed": "StatusCheckFailed",
    "ReadLatency": "ReadLatency",
    "WriteLatency": "WriteLatency",
    "ELB5XX": "HTTPCode_ELB_5XX_Count",
    "TargetResponseTime": "TargetResponseTime",
    "TCPClientReset": "TCP_Client_Reset_Count",
    "TCPTargetReset": "TCP_Target_Reset_Count",
    "RequestCountPerTarget": "RequestCountPerTarget",
    "TGResponseTime": "TargetResponseTime",
}

# 메트릭별 방향/단위
_METRIC_DIRECTION_UNIT = {
    "CPU": (">", "%"),
    "Memory": (">", "%"),
    "Disk": (">", "%"),
    "FreeMemoryGB": ("<", "GB"),
    "FreeStorageGB": ("<", "GB"),
    "Connections": (">", ""),
    "RequestCount": (">", ""),
    "HealthyHostCount": ("<", ""),
    "UnHealthyHostCount": (">", ""),
    "ProcessedBytes": (">", ""),
    "ActiveFlowCount": (">", ""),
    "NewFlowCount": (">", ""),
    "StatusCheckFailed": (">", ""),
    "ReadLatency": (">", "s"),
    "WriteLatency": (">", "s"),
    "ELB5XX": (">", ""),
    "TargetResponseTime": (">", "s"),
    "TCPClientReset": (">", ""),
    "TCPTargetReset": (">", ""),
    "RequestCountPerTarget": (">", ""),
    "TGResponseTime": (">", "s"),
}

# resource_type별 샘플 resource_id
_RESOURCE_IDS = {
    "EC2": "i-0abc123def456789a",
    "RDS": "db-test-preserve",
    "ALB": (
        "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
        "loadbalancer/app/my-alb/1234567890abcdef"
    ),
    "NLB": (
        "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
        "loadbalancer/net/my-nlb/1234567890abcdef"
    ),
    "TG": (
        "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
        "targetgroup/my-tg/1234567890abcdef"
    ),
}

_ENV = {
    "ENVIRONMENT": "prod",
    "SNS_TOPIC_ARN_ALERT": "",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
}

# GB → bytes 변환 대상 메트릭
_GB_TO_BYTES_METRICS = {"FreeMemoryGB", "FreeStorageGB"}


# ──────────────────────────────────────────────
# Hypothesis 전략
# ──────────────────────────────────────────────

# 양의 숫자 임계치 (정수 범위로 제한하여 표시 안정성 확보)
positive_thresholds = st.floats(
    min_value=1.0,
    max_value=9999.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda x: round(x, 2))

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])

# 리소스 이름 (알람 이름 label로 사용)
resource_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=30,
)


@st.composite
def hardcoded_only_tags(draw):
    """하드코딩 메트릭만 포함하는 태그 조합 생성."""
    rtype = draw(resource_types)
    name = draw(resource_names)
    metrics = _HARDCODED_METRICS[rtype]

    tags = {"Monitoring": "on", "Name": name}

    # TG 리소스는 _lb_arn, _lb_type 태그 필수 (복합 디멘션 생성에 사용)
    if rtype == "TG":
        tags["_lb_arn"] = (
            "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
            "loadbalancer/app/my-alb/1234567890abcdef"
        )
        tags["_lb_type"] = "application"

    # 각 하드코딩 메트릭에 대해 임계치 태그 생성 (Disk 제외)
    for metric in metrics:
        if metric == "Disk":
            # Disk는 Threshold_Disk_root 형태
            thr = draw(positive_thresholds)
            tags["Threshold_Disk_root"] = str(int(thr)) if thr == int(thr) else str(thr)
        else:
            thr = draw(positive_thresholds)
            tags[f"Threshold_{metric}"] = str(int(thr)) if thr == int(thr) else str(thr)

    return rtype, tags


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _register_cwagent_disk_metric(instance_id: str):
    """EC2 Disk 알람을 위해 CWAgent disk_used_percent 메트릭 등록."""
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    cw.put_metric_data(
        Namespace="CWAgent",
        MetricData=[
            {
                "MetricName": "disk_used_percent",
                "Dimensions": [
                    {"Name": "InstanceId", "Value": instance_id},
                    {"Name": "path", "Value": "/"},
                    {"Name": "device", "Value": "xvda1"},
                    {"Name": "fstype", "Value": "xfs"},
                ],
                "Value": 42.0,
                "Unit": "Percent",
            }
        ],
    )


def _format_threshold_str(threshold: float) -> str:
    """임계치를 알람 이름에 사용되는 문자열로 변환."""
    if threshold == int(threshold):
        return str(int(threshold))
    return f"{threshold:g}"


def _get_expected_alarm_name(
    resource_type: str,
    resource_id: str,
    label: str,
    metric: str,
    threshold: float,
) -> str:
    """기대되는 알람 이름 생성."""
    direction, unit = _METRIC_DIRECTION_UNIT[metric]

    if metric == "Disk":
        display = "disk_used_percent(/)"
    else:
        display = _METRIC_DISPLAY[metric]

    thr_str = _format_threshold_str(threshold)
    return (
        f"[{resource_type}] {label} {display} "
        f"{direction}{thr_str}{unit} ({resource_id})"
    )


# ──────────────────────────────────────────────
# 알람 이름 포맷 정규식
# ──────────────────────────────────────────────

_ALARM_NAME_PATTERN = re.compile(
    r"^\[(?P<rtype>\w+)\] "
    r"(?P<label>.+?) "
    r"(?P<display>\S+(?:\(/?\S*\))?)"
    r" (?P<dir>[><])(?P<thr>[\d.]+)(?P<unit>[%A-Za-z]*)"
    r" \((?P<rid>.+)\)$"
)


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestHardcodedAlarmPreservation:
    """
    하드코딩 메트릭만 포함하는 태그 조합에 대해
    create_alarms_for_resource()가 기존 동작을 보존하는지 검증.

    **Validates: Requirements 3.1, 3.2, 3.6, 3.7, 3.8**
    """

    @given(data=hardcoded_only_tags())
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_alarm_count_and_format_preserved(self, data):
        """
        **Property 2: Preservation** - 알람 개수, 이름 포맷, 임계치, 네임스페이스 보존

        하드코딩 메트릭만 포함하는 태그 조합에 대해:
        1. 알람 개수가 resource_type별 기대값과 일치
        2. 알람 이름이 규정 포맷을 따름
        3. 임계치가 태그 값과 일치 (GB→bytes 변환 포함)
        4. 네임스페이스가 메트릭별 기대값과 일치

        **Validates: Requirements 3.1, 3.2, 3.6, 3.7, 3.8**
        """
        resource_type, tags = data
        resource_id = _RESOURCE_IDS[resource_type]

        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            # EC2 Disk 알람을 위해 CWAgent 메트릭 등록
            if resource_type == "EC2":
                _register_cwagent_disk_metric(resource_id)

            result = create_alarms_for_resource(
                resource_id, resource_type, tags,
            )

        # ── 1. 알람 개수 검증 ──
        expected_count = _EXPECTED_ALARM_COUNTS[resource_type]
        assert len(result) == expected_count, (
            f"알람 개수 불일치: expected={expected_count}, "
            f"actual={len(result)}\n"
            f"resource_type={resource_type}, tags={tags}\n"
            f"생성된 알람: {result}"
        )

        # ── 2. 알람 이름 포맷 검증 ──
        label = tags.get("Name", resource_id)
        for alarm_name in result:
            match = _ALARM_NAME_PATTERN.match(alarm_name)
            assert match is not None, (
                f"알람 이름이 규정 포맷과 불일치: {alarm_name}\n"
                f"기대 포맷: [{resource_type}] {{label}} "
                f"{{display_metric}} {{dir}}{{thr}}{{unit}} "
                f"({resource_id})"
            )
            # resource_type 일치
            assert match.group("rtype") == resource_type, (
                f"resource_type 불일치: "
                f"expected={resource_type}, "
                f"actual={match.group('rtype')}"
            )
            # resource_id 일치 (ALB/NLB/TG는 Short_ID로 변환됨)
            expected_rid = _shorten_elb_resource_id(resource_id, resource_type)
            assert match.group("rid") == expected_rid, (
                f"resource_id 불일치: "
                f"expected={expected_rid}, "
                f"actual={match.group('rid')}"
            )

        # ── 3. 메트릭별 알람 존재 및 임계치 검증 ──
        metrics = _HARDCODED_METRICS[resource_type]
        for metric in metrics:
            display = _METRIC_DISPLAY[metric]

            if metric == "Disk":
                # Disk 알람은 display_name(/) 형태
                matching = [
                    a for a in result
                    if f"{display}(/)" in a
                ]
            else:
                matching = [
                    a for a in result
                    if _ALARM_NAME_PATTERN.match(a)
                    and _ALARM_NAME_PATTERN.match(a).group("display") == display
                ]

            assert len(matching) >= 1, (
                f"메트릭 '{metric}' ({display}) 알람 미발견\n"
                f"생성된 알람: {result}"
            )

            # 임계치 검증
            alarm_name = matching[0]
            m = _ALARM_NAME_PATTERN.match(alarm_name)
            assert m is not None

            actual_thr_str = m.group("thr")
            actual_thr = float(actual_thr_str)

            if metric == "Disk":
                tag_key = "Threshold_Disk_root"
            else:
                tag_key = f"Threshold_{metric}"

            expected_thr = float(tags[tag_key])

            # 알람 이름의 임계치는 원본 값 (GB 단위)
            assert abs(actual_thr - expected_thr) < 0.01, (
                f"임계치 불일치 (metric={metric}): "
                f"expected={expected_thr}, actual={actual_thr}\n"
                f"alarm_name={alarm_name}"
            )

            # 방향/단위 검증
            expected_dir, expected_unit = _METRIC_DIRECTION_UNIT[metric]
            assert m.group("dir") == expected_dir, (
                f"방향 불일치 (metric={metric}): "
                f"expected={expected_dir}, "
                f"actual={m.group('dir')}"
            )
            assert m.group("unit") == expected_unit, (
                f"단위 불일치 (metric={metric}): "
                f"expected={expected_unit}, "
                f"actual={m.group('unit')}"
            )

    @given(data=hardcoded_only_tags())
    @settings(
        max_examples=10,
        deadline=None,
        suppress_health_check=[HealthCheck.filter_too_much],
    )
    @mock_aws
    def test_rds_gb_to_bytes_conversion(self, data):
        """
        **Property 2: Preservation** - RDS GB→bytes 변환 보존

        RDS FreeMemoryGB/FreeStorageGB 알람의 CloudWatch 임계치가
        GB→bytes 변환이 적용되었는지 검증.

        **Validates: Requirements 3.7**
        """
        resource_type, tags = data
        assume(resource_type == "RDS")

        resource_id = _RESOURCE_IDS[resource_type]
        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            result = create_alarms_for_resource(
                resource_id, resource_type, tags,
            )

        # describe_alarms로 실제 CloudWatch 임계치 확인
        cw = boto3.client("cloudwatch", region_name="us-east-1")

        for metric in ("FreeMemoryGB", "FreeStorageGB"):
            display = _METRIC_DISPLAY[metric]
            matching = [a for a in result if display in a]
            assert len(matching) == 1, (
                f"RDS {metric} 알람 미발견: {result}"
            )

            resp = cw.describe_alarms(AlarmNames=[matching[0]])
            alarms = resp.get("MetricAlarms", [])
            assert len(alarms) == 1

            cw_threshold = alarms[0]["Threshold"]
            tag_gb = float(tags[f"Threshold_{metric}"])
            expected_bytes = tag_gb * 1024 * 1024 * 1024

            assert abs(cw_threshold - expected_bytes) < 1.0, (
                f"GB→bytes 변환 불일치 (metric={metric}): "
                f"tag_gb={tag_gb}, "
                f"expected_bytes={expected_bytes}, "
                f"cw_threshold={cw_threshold}"
            )

    @given(data=hardcoded_only_tags())
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_threshold_fallback_priority(self, data):
        """
        **Property 2: Preservation** - 임계치 3단계 폴백 우선순위 보존

        태그 임계치가 환경변수/하드코딩 기본값보다 우선하는지 검증.

        **Validates: Requirements 3.2**
        """
        resource_type, tags = data
        resource_id = _RESOURCE_IDS[resource_type]

        _get_cw_client.cache_clear()

        # 환경변수에 다른 값 설정 (태그가 우선해야 함)
        env_with_defaults = dict(_ENV)
        env_with_defaults["DEFAULT_CPU_THRESHOLD"] = "99"
        env_with_defaults["DEFAULT_MEMORY_THRESHOLD"] = "99"
        env_with_defaults["DEFAULT_CONNECTIONS_THRESHOLD"] = "9999"
        env_with_defaults["DEFAULT_DISK_THRESHOLD"] = "99"
        env_with_defaults["DEFAULT_FREEMEMORYGB_THRESHOLD"] = "99"
        env_with_defaults["DEFAULT_FREESTORAGEGB_THRESHOLD"] = "99"
        env_with_defaults["DEFAULT_REQUESTCOUNT_THRESHOLD"] = "99999"

        with pytest.MonkeyPatch.context() as mp:
            for k, v in env_with_defaults.items():
                mp.setenv(k, v)

            if resource_type == "EC2":
                _register_cwagent_disk_metric(resource_id)

            result = create_alarms_for_resource(
                resource_id, resource_type, tags,
            )

        # 각 메트릭의 알람 이름에서 임계치가 태그 값과 일치하는지 확인
        metrics = _HARDCODED_METRICS[resource_type]
        for metric in metrics:
            display = _METRIC_DISPLAY[metric]

            if metric == "Disk":
                matching = [a for a in result if f"{display}(/)" in a]
                tag_key = "Threshold_Disk_root"
            else:
                # 정규식으로 display 메트릭 부분만 정확히 매칭
                # 알람 이름 포맷: [TYPE] label display dir+thr+unit (rid)
                matching = [
                    a for a in result
                    if _ALARM_NAME_PATTERN.match(a)
                    and _ALARM_NAME_PATTERN.match(a).group("display") == display
                ]
                tag_key = f"Threshold_{metric}"

            assert len(matching) >= 1, (
                f"메트릭 '{metric}' 알람 미발견: {result}"
            )

            m = _ALARM_NAME_PATTERN.match(matching[0])
            assert m is not None

            actual_thr = float(m.group("thr"))
            expected_thr = float(tags[tag_key])

            assert abs(actual_thr - expected_thr) < 0.01, (
                f"태그 임계치가 환경변수보다 우선하지 않음 "
                f"(metric={metric}): "
                f"tag={expected_thr}, actual={actual_thr}\n"
                f"환경변수 DEFAULT_{metric.upper()}_THRESHOLD=99"
            )
