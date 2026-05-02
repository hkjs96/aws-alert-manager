"""
Property-Based Tests: Tag-Driven Alarm Engine

아래 8개 Property를 검증한다. 기존 PBT에서 다루지 않는 갭을 채운다.

P1: LT_ prefix → comparison=LessThanThreshold 보존
P2: Threshold_X=off → 해당 메트릭 동적 알람 억제
P3: N개 고유 메트릭명 → N개 고유 result 키 (충돌 없음)
P4: CW metric_name 별칭 필터링 (KI-005 회귀 방지)
P5: CW metric_name 별칭 전수 — _metric_name_to_key 매핑 전체 커버
P6: 하드코딩 + 동적 알람 공존 (moto)
P7: 임계치 폴백 체인 — 환경변수 > 하드코딩 기본값 (태그 없을 때)
P8: sync_alarms — 태그 삭제 시 동적 알람 정리
"""

import os
from unittest.mock import patch

import boto3
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from moto import mock_aws

from common.alarm_manager import (
    _get_cw_client,
    _parse_threshold_tags,
    create_alarms_for_resource,
    sync_alarms_for_resource,
)
from common.alarm_registry import _get_alarm_defs

# ──────────────────────────────────────────────
# 공통 상수
# ──────────────────────────────────────────────

_RESOURCE_IDS = {
    "EC2": "i-0abc123def456789a",
    "RDS": "db-test-pbt-tag-driven",
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

_HARDCODED_METRICS: dict[str, set[str]] = {
    rt: {d["metric"] for d in _get_alarm_defs(rt)}
    for rt in ["EC2", "RDS", "ALB", "NLB", "TG"]
}

# _NAMESPACE_MAP: 동적 알람 등록용 (namespace, dimension_key)
_NAMESPACE_MAP = {
    "EC2": ("AWS/EC2", "InstanceId"),
    "RDS": ("AWS/RDS", "DBInstanceIdentifier"),
    "ALB": ("AWS/ApplicationELB", "LoadBalancer"),
    "NLB": ("AWS/NetworkELB", "LoadBalancer"),
    "TG": ("AWS/ApplicationELB", "TargetGroup"),
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

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])

# 동적 메트릭 이름 — 하드코딩 목록에 없는 것들
_DYNAMIC_CANDIDATES = [
    "NetworkIn",
    "NetworkOut",
    "DiskReadOps",
    "DiskWriteOps",
    "NetworkPacketsIn",
    "NetworkPacketsOut",
    "ActiveConnectionCount",
    "NewConnectionCount",
    "ConsumedReadCapacityUnits",
    "BurstBalance",
    "ReadIOPS",
    "WriteIOPS",
]

positive_thresholds = st.floats(
    min_value=0.1, max_value=99999.0, allow_nan=False, allow_infinity=False,
)


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _dynamic_candidates_for(resource_type: str) -> list[str]:
    hardcoded = _HARDCODED_METRICS[resource_type]
    return [m for m in _DYNAMIC_CANDIDATES if m not in hardcoded]


def _register_dynamic_metric_in_cw(resource_type: str, metric_name: str) -> None:
    """moto CW에 동적 메트릭 데이터포인트를 등록한다."""
    resource_id = _RESOURCE_IDS[resource_type]
    namespace, dimension_key = _NAMESPACE_MAP[resource_type]

    if resource_type in ("ALB", "NLB"):
        dim_value = resource_id.split("loadbalancer/", 1)[1]
    elif resource_type == "TG":
        parts = resource_id.split(":targetgroup/", 1)
        dim_value = "targetgroup/" + parts[1]
    else:
        dim_value = resource_id

    cw = boto3.client("cloudwatch", region_name="us-east-1")
    cw.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric_name,
            "Dimensions": [{"Name": dimension_key, "Value": dim_value}],
            "Value": 42.0,
            "Unit": "None",
        }],
    )


def _base_tags(resource_type: str) -> dict:
    tags: dict = {"Monitoring": "on", "Name": "test-resource"}
    if resource_type == "TG":
        tags["_lb_arn"] = (
            "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
            "loadbalancer/app/my-alb/1234567890abcdef"
        )
        tags["_lb_type"] = "application"
    return tags


# ──────────────────────────────────────────────
# P1: LT_ prefix → LessThanThreshold 보존
# ──────────────────────────────────────────────

class TestLtPrefixDirectionPreservation:
    """
    P1: Threshold_LT_{MetricName}={Value} 태그에서
    comparison_operator가 'LessThanThreshold'로 반환되어야 한다.
    """

    @given(resource_type=resource_types, threshold=positive_thresholds)
    @settings(max_examples=30, deadline=None)
    def test_lt_prefix_returns_less_than_threshold(self, resource_type, threshold):
        """LT_ prefix → comparison='LessThanThreshold'."""
        metric = _dynamic_candidates_for(resource_type)[0]
        thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
        tags = {
            "Monitoring": "on",
            f"Threshold_LT_{metric}": thr_str,
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert metric in result, (
            f"LT_ prefix metric '{metric}' not found in result.\n"
            f"tags={tags}\nresult={result}"
        )
        _, comparison = result[metric]
        assert comparison == "LessThanThreshold", (
            f"Expected 'LessThanThreshold' for Threshold_LT_{metric}, "
            f"got {comparison!r}"
        )

    @given(resource_type=resource_types, threshold=positive_thresholds)
    @settings(max_examples=30, deadline=None)
    def test_no_lt_prefix_returns_greater_than_threshold(self, resource_type, threshold):
        """LT_ prefix 없으면 comparison='GreaterThanThreshold'."""
        metric = _dynamic_candidates_for(resource_type)[0]
        thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
        tags = {
            "Monitoring": "on",
            f"Threshold_{metric}": thr_str,
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert metric in result
        _, comparison = result[metric]
        assert comparison == "GreaterThanThreshold", (
            f"Expected 'GreaterThanThreshold' for Threshold_{metric}, "
            f"got {comparison!r}"
        )

    @given(resource_type=resource_types, threshold=positive_thresholds)
    @settings(max_examples=20, deadline=None)
    def test_lt_threshold_value_preserved(self, resource_type, threshold):
        """LT_ prefix를 써도 임계치 수치는 그대로 보존된다."""
        metric = _dynamic_candidates_for(resource_type)[0]
        thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
        tags = {"Monitoring": "on", f"Threshold_LT_{metric}": thr_str}

        result = _parse_threshold_tags(tags, resource_type)

        assert metric in result
        actual_thr, _ = result[metric]
        assert abs(actual_thr - float(thr_str)) < 0.001, (
            f"Threshold value mismatch: tag={thr_str}, result={actual_thr}"
        )


# ──────────────────────────────────────────────
# P2: "off" 태그 → 동적 알람 억제
# ──────────────────────────────────────────────

class TestOffTagSuppression:
    """
    P2: Threshold_{MetricName}=off 이면 해당 메트릭은 동적 알람 대상에서 제외된다.
    """

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_off_value_suppresses_dynamic_metric(self, resource_type):
        """Threshold_X=off → X not in result."""
        metric = _dynamic_candidates_for(resource_type)[0]
        tags = {
            "Monitoring": "on",
            f"Threshold_{metric}": "off",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert metric not in result, (
            f"'off' 태그를 가진 메트릭 '{metric}'이 result에 포함됨.\n"
            f"result={result}"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_off_case_insensitive(self, resource_type):
        """Threshold_X=OFF, Off, oFf 모두 억제된다."""
        metric = _dynamic_candidates_for(resource_type)[0]
        for off_value in ("OFF", "Off", "oFf", " off ", "off "):
            tags = {"Monitoring": "on", f"Threshold_{metric}": off_value}
            result = _parse_threshold_tags(tags, resource_type)
            assert metric not in result, (
                f"'{off_value}' 태그를 가진 메트릭 '{metric}'이 result에 포함됨."
            )

    @given(resource_type=resource_types, threshold=positive_thresholds)
    @settings(max_examples=20, deadline=None)
    def test_other_metrics_not_affected_by_off(self, resource_type, threshold):
        """한 메트릭의 off 태그가 다른 메트릭에 영향을 주지 않는다."""
        candidates = _dynamic_candidates_for(resource_type)
        assume(len(candidates) >= 2)
        metric_a, metric_b = candidates[0], candidates[1]
        thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
        tags = {
            "Monitoring": "on",
            f"Threshold_{metric_a}": "off",
            f"Threshold_{metric_b}": thr_str,
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert metric_a not in result
        assert metric_b in result, (
            f"off 태그와 무관한 메트릭 '{metric_b}'이 result에서 제외됨.\n"
            f"result={result}"
        )


# ──────────────────────────────────────────────
# P3: N개 고유 메트릭명 → N개 고유 result 키
# ──────────────────────────────────────────────

class TestDynamicMetricKeyUniqueness:
    """
    P3: 서로 다른 N개 동적 메트릭 태그 → result dict에 N개 고유 키.
    Threshold_ 태그 충돌이나 오버라이트가 없어야 한다.
    """

    @given(
        resource_type=resource_types,
        n=st.integers(min_value=2, max_value=4),
        thresholds=st.lists(
            st.floats(min_value=0.1, max_value=9999.0, allow_nan=False, allow_infinity=False),
            min_size=4, max_size=4,
        ),
    )
    @settings(max_examples=20, deadline=None)
    def test_n_distinct_metrics_yield_n_distinct_keys(self, resource_type, n, thresholds):
        """N개 고유 메트릭 태그 → result에 N개 고유 키."""
        candidates = _dynamic_candidates_for(resource_type)
        assume(len(candidates) >= n)

        selected = candidates[:n]
        tags = {"Monitoring": "on"}
        for i, metric in enumerate(selected):
            thr = thresholds[i]
            tags[f"Threshold_{metric}"] = str(int(thr)) if thr == int(thr) else str(thr)

        result = _parse_threshold_tags(tags, resource_type)

        for metric in selected:
            assert metric in result, (
                f"메트릭 '{metric}'이 result에 없음.\n"
                f"tags={tags}\nresult={result}"
            )

        result_keys_from_selected = [k for k in result if k in selected]
        assert len(result_keys_from_selected) == n, (
            f"result 키 개수 불일치: expected={n}, actual={len(result_keys_from_selected)}\n"
            f"result={result}"
        )


# ──────────────────────────────────────────────
# P4: CW metric_name 별칭 필터링 (KI-005 회귀 방지)
# ──────────────────────────────────────────────

class TestCwMetricNameAliasFiltering:
    """
    P4/P5: KI-005 — CW metric_name을 Threshold_ 태그에 사용하면
    하드코딩 알람과 중복 동적 알람이 생성되지 않도록 필터링된다.

    예) EC2에서 Threshold_CPUUtilization=10 →
        _metric_name_to_key("CPUUtilization") = "CPU" (hardcoded) → skip
    """

    @given(resource_type=resource_types)
    @settings(max_examples=10, deadline=None)
    def test_cpu_utilization_alias_filtered_for_ec2(self, resource_type):
        """Threshold_CPUUtilization은 EC2 하드코딩 CPU 알람과 중복 — 동적 알람에서 제외."""
        assume(resource_type == "EC2")
        tags = {
            "Monitoring": "on",
            "Threshold_CPUUtilization": "10",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert "CPUUtilization" not in result, (
            "Threshold_CPUUtilization은 EC2 하드코딩 CPU 알람과 중복이므로 "
            "동적 알람에서 제외되어야 한다. (KI-005)\n"
            f"result={result}"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=10, deadline=None)
    def test_free_storage_space_alias_filtered_for_rds(self, resource_type):
        """Threshold_FreeStorageSpace는 RDS 하드코딩 FreeStorageGB와 중복 — 제외."""
        assume(resource_type == "RDS")
        tags = {
            "Monitoring": "on",
            "Threshold_FreeStorageSpace": "10",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert "FreeStorageSpace" not in result, (
            "Threshold_FreeStorageSpace는 RDS 하드코딩 FreeStorageGB 알람과 중복. (KI-005)\n"
            f"result={result}"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=10, deadline=None)
    def test_http_elb_5xx_alias_filtered_for_alb(self, resource_type):
        """Threshold_HTTPCode_ELB_5XX_Count는 ALB 하드코딩 ELB5XX와 중복 — 제외."""
        assume(resource_type == "ALB")
        tags = {
            "Monitoring": "on",
            "Threshold_HTTPCode_ELB_5XX_Count": "50",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert "HTTPCode_ELB_5XX_Count" not in result, (
            "Threshold_HTTPCode_ELB_5XX_Count는 ALB 하드코딩 ELB5XX와 중복. (KI-005)\n"
            f"result={result}"
        )

    def test_all_known_cw_aliases_filtered(self):
        """
        P5: _metric_name_to_key에 매핑된 CW metric_name 전체에 대해
        해당 resource_type에서 동적 알람 결과에 포함되지 않는지 검증.

        내부 키가 하드코딩 목록에 있는 CW metric_name만 테스트.
        """
        # (resource_type, cw_metric_name, internal_key)
        test_cases = [
            ("EC2", "CPUUtilization", "CPU"),
            ("EC2", "mem_used_percent", "Memory"),
            ("RDS", "CPUUtilization", "CPU"),
            ("RDS", "FreeableMemory", "FreeMemoryGB"),
            ("RDS", "FreeStorageSpace", "FreeStorageGB"),
            ("RDS", "DatabaseConnections", "Connections"),
            ("ALB", "HTTPCode_ELB_5XX_Count", "ELB5XX"),
            ("ALB", "RequestCount", "RequestCount"),
            ("NLB", "ProcessedBytes", "ProcessedBytes"),
            ("NLB", "TCP_Client_Reset_Count", "TCPClientReset"),
            ("TG", "HealthyHostCount", "HealthyHostCount"),
            ("TG", "UnHealthyHostCount", "UnHealthyHostCount"),
        ]
        for resource_type, cw_name, internal_key in test_cases:
            hardcoded = _HARDCODED_METRICS[resource_type]
            if internal_key not in hardcoded:
                continue  # 이 resource_type에서 하드코딩 아니면 skip

            tags = {"Monitoring": "on", f"Threshold_{cw_name}": "100"}
            result = _parse_threshold_tags(tags, resource_type)

            assert cw_name not in result, (
                f"KI-005 위반: Threshold_{cw_name}이 {resource_type}의 동적 알람으로 처리됨. "
                f"내부 키 '{internal_key}'는 하드코딩 목록에 있어 중복 알람 생성을 유발함.\n"
                f"result={result}"
            )


# ──────────────────────────────────────────────
# P6: 하드코딩 + 동적 알람 공존 (moto)
# ──────────────────────────────────────────────

class TestHardcodedAndDynamicCoexistence:
    """
    P6: 하드코딩 메트릭 태그 + 동적 메트릭 태그가 동시에 있을 때
    create_alarms_for_resource() 결과에 둘 다 포함된다.
    """

    @given(
        resource_type=st.sampled_from(["EC2", "RDS"]),
        threshold=st.floats(min_value=1.0, max_value=9000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
    @mock_aws
    def test_hardcoded_and_dynamic_both_in_result(self, resource_type, threshold):
        """하드코딩 알람 N개 + 동적 알람 1개 → 결과에 N+1개 이상."""
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS[resource_type]
        dynamic_metric = _dynamic_candidates_for(resource_type)[0]

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            _register_dynamic_metric_in_cw(resource_type, dynamic_metric)

            thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
            tags = _base_tags(resource_type)
            tags[f"Threshold_{dynamic_metric}"] = thr_str

            # EC2 Disk를 위한 CWAgent 메트릭 등록
            if resource_type == "EC2":
                cw = boto3.client("cloudwatch", region_name="us-east-1")
                cw.put_metric_data(
                    Namespace="CWAgent",
                    MetricData=[{
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": resource_id},
                            {"Name": "path", "Value": "/"},
                            {"Name": "device", "Value": "xvda1"},
                            {"Name": "fstype", "Value": "xfs"},
                        ],
                        "Value": 42.0,
                        "Unit": "Percent",
                    }],
                )

            result = create_alarms_for_resource(resource_id, resource_type, tags)

        hardcoded_count = len(_get_alarm_defs(resource_type))
        assert len(result) >= hardcoded_count + 1, (
            f"하드코딩({hardcoded_count}) + 동적(1) 알람이 모두 생성되지 않음.\n"
            f"생성된 알람 수: {len(result)}\n"
            f"생성된 알람: {result}"
        )
        # 동적 알람이 결과에 포함되어야 함
        dynamic_in_result = any(dynamic_metric in name for name in result)
        assert dynamic_in_result, (
            f"동적 알람 '{dynamic_metric}'이 결과에 없음.\n"
            f"생성된 알람: {result}"
        )


# ──────────────────────────────────────────────
# P7: 임계치 폴백 — 환경변수 > 하드코딩 기본값
# ──────────────────────────────────────────────

class TestThresholdFallbackChain:
    """
    P7: 임계치 폴백 체인:
      (a) 태그 없고 환경변수 있으면 → 환경변수 값 사용
      (b) 태그도 없고 환경변수도 없으면 → HARDCODED_DEFAULTS 사용

    기존 test_pbt_dynamic_alarm_preservation.py가 태그 > 환경변수를 커버하므로
    여기서는 (a) 환경변수 > 하드코딩, (b) 하드코딩 최종 폴백을 검증.
    """

    @mock_aws
    def test_env_var_overrides_hardcoded_default(self):
        """
        태그 없이 환경변수만 있을 때 환경변수 임계치가 알람에 반영된다.
        CPU 기본값=80%, 환경변수=50% 설정 후 알람 임계치=50 검증.
        """
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS["EC2"]
        env = dict(_ENV)
        env["DEFAULT_CPU_THRESHOLD"] = "50"

        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            tags = _base_tags("EC2")

            # CWAgent 메트릭 등록 (Disk 알람을 위해)
            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": resource_id},
                        {"Name": "path", "Value": "/"},
                        {"Name": "device", "Value": "xvda1"},
                        {"Name": "fstype", "Value": "xfs"},
                    ],
                    "Value": 42.0, "Unit": "Percent",
                }],
            )
            result = create_alarms_for_resource(resource_id, "EC2", tags)

        # CPU 알람 찾기
        cpu_alarms = [n for n in result if "CPUUtilization" in n]
        assert len(cpu_alarms) == 1, f"CPU 알람 미발견: {result}"

        # 알람 이름에서 임계치 추출: ">50%"
        alarm_name = cpu_alarms[0]
        assert "> 50%" in alarm_name, (
            f"환경변수 CPU 임계치(50%)가 알람 이름에 반영되지 않음.\n"
            f"alarm_name={alarm_name}"
        )

    @mock_aws
    def test_hardcoded_default_when_no_tag_no_env_var(self):
        """
        태그도 없고 환경변수도 없을 때 HARDCODED_DEFAULTS(CPU=80%) 사용.
        """
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS["EC2"]

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            mp.delenv("DEFAULT_CPU_THRESHOLD", raising=False)

            tags = _base_tags("EC2")
            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": resource_id},
                        {"Name": "path", "Value": "/"},
                        {"Name": "device", "Value": "xvda1"},
                        {"Name": "fstype", "Value": "xfs"},
                    ],
                    "Value": 42.0, "Unit": "Percent",
                }],
            )
            result = create_alarms_for_resource(resource_id, "EC2", tags)

        cpu_alarms = [n for n in result if "CPUUtilization" in n]
        assert len(cpu_alarms) == 1, f"CPU 알람 미발견: {result}"

        alarm_name = cpu_alarms[0]
        assert "> 80%" in alarm_name, (
            f"HARDCODED_DEFAULT CPU 임계치(80%)가 알람 이름에 반영되지 않음.\n"
            f"alarm_name={alarm_name}"
        )

    @given(
        env_threshold=st.floats(min_value=10.0, max_value=95.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_env_var_any_value_overrides_hardcoded(self, env_threshold):
        """임의의 환경변수 임계치 값이 하드코딩 기본값(80%)보다 우선 적용된다."""
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS["EC2"]
        env = dict(_ENV)
        thr_int = int(round(env_threshold))
        env["DEFAULT_CPU_THRESHOLD"] = str(thr_int)

        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)

            tags = _base_tags("EC2")
            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": resource_id},
                        {"Name": "path", "Value": "/"},
                        {"Name": "device", "Value": "xvda1"},
                        {"Name": "fstype", "Value": "xfs"},
                    ],
                    "Value": 42.0, "Unit": "Percent",
                }],
            )
            result = create_alarms_for_resource(resource_id, "EC2", tags)

        cpu_alarms = [n for n in result if "CPUUtilization" in n]
        assert len(cpu_alarms) == 1, f"CPU 알람 미발견: {result}"
        assert f"> {thr_int}%" in cpu_alarms[0], (
            f"환경변수 임계치({thr_int}%)가 알람 이름에 없음: {cpu_alarms[0]}"
        )


# ──────────────────────────────────────────────
# P8: sync_alarms — 태그 삭제 시 동적 알람 정리
# ──────────────────────────────────────────────

class TestSyncRemovesAlarmsOnTagDeletion:
    """
    P8: 동적 메트릭 태그를 추가한 뒤 해당 태그를 제거하고 sync하면
    해당 동적 알람이 deleted 목록에 들어가고 CloudWatch에서도 삭제된다.
    """

    @given(
        threshold=st.floats(min_value=0.1, max_value=9999.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=10, deadline=None)
    @mock_aws
    def test_dynamic_alarm_deleted_when_tag_removed(self, threshold):
        """Threshold_X 태그 삭제 후 sync → X 알람이 deleted에 포함."""
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS["EC2"]
        dynamic_metric = _dynamic_candidates_for("EC2")[0]

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            _register_dynamic_metric_in_cw("EC2", dynamic_metric)

            # EC2 Disk CWAgent 메트릭
            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": resource_id},
                        {"Name": "path", "Value": "/"},
                        {"Name": "device", "Value": "xvda1"},
                        {"Name": "fstype", "Value": "xfs"},
                    ],
                    "Value": 42.0, "Unit": "Percent",
                }],
            )

            thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
            tags_with_dynamic = _base_tags("EC2")
            tags_with_dynamic[f"Threshold_{dynamic_metric}"] = thr_str

            # 1단계: 동적 태그 포함하여 알람 생성
            created = create_alarms_for_resource(resource_id, "EC2", tags_with_dynamic)
            dynamic_alarms_created = [n for n in created if dynamic_metric in n]
            assert len(dynamic_alarms_created) >= 1, (
                f"동적 알람이 생성되지 않음: created={created}"
            )

            # 2단계: 동적 태그 제거 후 sync
            _get_cw_client.cache_clear()
            tags_without_dynamic = _base_tags("EC2")
            sync_result = sync_alarms_for_resource(resource_id, "EC2", tags_without_dynamic)

        deleted = sync_result.get("deleted", [])
        assert any(dynamic_metric in name for name in deleted), (
            f"태그 삭제 후 sync에서 동적 알람이 deleted에 없음.\n"
            f"dynamic_metric={dynamic_metric}\n"
            f"deleted={deleted}\n"
            f"sync_result={sync_result}"
        )

    @mock_aws
    def test_remaining_hardcoded_alarms_not_deleted(self):
        """동적 태그 삭제 시 하드코딩 알람은 삭제되지 않는다."""
        _get_cw_client.cache_clear()
        resource_id = _RESOURCE_IDS["RDS"]
        dynamic_metric = _dynamic_candidates_for("RDS")[0]

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            _register_dynamic_metric_in_cw("RDS", dynamic_metric)

            tags_with_dynamic = _base_tags("RDS")
            tags_with_dynamic[f"Threshold_{dynamic_metric}"] = "100"

            create_alarms_for_resource(resource_id, "RDS", tags_with_dynamic)

            _get_cw_client.cache_clear()
            tags_without_dynamic = _base_tags("RDS")
            sync_result = sync_alarms_for_resource(resource_id, "RDS", tags_without_dynamic)

        deleted = sync_result.get("deleted", [])
        ok_or_updated = sync_result.get("ok", []) + sync_result.get("updated", [])

        # 동적 알람만 삭제되고 하드코딩 알람은 ok/updated에 남아야 함
        dynamic_deleted = [n for n in deleted if dynamic_metric in n]
        assert len(dynamic_deleted) >= 1, (
            f"동적 알람({dynamic_metric})이 deleted에 없음: {deleted}"
        )

        hardcoded_metrics_cw_names = {
            "CPUUtilization", "FreeableMemory", "FreeStorageSpace",
            "DatabaseConnections", "ReadLatency", "WriteLatency",
        }
        hardcoded_wrongly_deleted = [
            n for n in deleted
            if any(m in n for m in hardcoded_metrics_cw_names)
        ]
        assert len(hardcoded_wrongly_deleted) == 0, (
            f"하드코딩 알람이 잘못 삭제됨: {hardcoded_wrongly_deleted}"
        )
