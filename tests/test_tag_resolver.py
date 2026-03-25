"""
Tag_Resolver 테스트 - Property 2, 3, 4, 13 속성 테스트 + 단위 테스트

Requirements: 2.1, 2.2, 2.3, 2.5
"""

import os
import pytest
from unittest.mock import patch

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from common.tag_resolver import get_threshold, has_monitoring_tag, is_threshold_off
from common import HARDCODED_DEFAULTS

# ──────────────────────────────────────────────
# 헬퍼 전략
# ──────────────────────────────────────────────

# 유효한 양의 숫자 문자열 전략
valid_positive_floats = st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False)

# 무효 태그 값 전략: 음수, 0, 비숫자 문자열, 빈 문자열
invalid_threshold_values = st.one_of(
    st.floats(max_value=0.0, allow_nan=False, allow_infinity=False).map(str),
    st.just("0"),
    st.just(""),
    st.just("abc"),
    st.just("-5"),
    st.just("none"),
    st.just("null"),
    st.text(min_size=1).filter(lambda s: not _is_valid_positive(s)),
)


def _is_valid_positive(s: str) -> bool:
    try:
        return float(s) > 0
    except (ValueError, TypeError):
        return False


METRIC_NAMES = ["CPU", "Memory", "Connections"]


# ──────────────────────────────────────────────
# Property 2: 태그 임계치 우선 적용
# Validates: Requirements 2.1
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    metric=st.sampled_from(METRIC_NAMES),
    tag_val=valid_positive_floats,
    env_val=valid_positive_floats,
)
def test_property_2_tag_takes_priority_over_env(metric, tag_val, env_val):
    """Feature: aws-monitoring-engine, Property 2: 태그 임계치 우선 적용"""
    assume(tag_val != env_val)  # 같으면 구분 불가

    tags = {f"Threshold_{metric}": str(tag_val)}
    env_key = f"DEFAULT_{metric.upper()}_THRESHOLD"

    with patch.dict(os.environ, {env_key: str(env_val)}):
        result = get_threshold(tags, metric)

    assert result == pytest.approx(tag_val), (
        f"태그 값 {tag_val}이 환경변수 {env_val}보다 우선해야 함, 실제: {result}"
    )


# ──────────────────────────────────────────────
# Property 3: 환경 변수 기본값 폴백
# Validates: Requirements 2.2
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    metric=st.sampled_from(METRIC_NAMES),
    env_val=valid_positive_floats,
)
def test_property_3_env_var_fallback(metric, env_val):
    """Feature: aws-monitoring-engine, Property 3: 환경 변수 기본값 폴백"""
    tags = {}  # 임계치 태그 없음
    env_key = f"DEFAULT_{metric.upper()}_THRESHOLD"

    with patch.dict(os.environ, {env_key: str(env_val)}, clear=False):
        result = get_threshold(tags, metric)

    assert result == pytest.approx(env_val), (
        f"태그 없을 때 환경변수 {env_val}이 반환되어야 함, 실제: {result}"
    )


# ──────────────────────────────────────────────
# Property 4: 잘못된 임계치 태그 무효 처리
# Validates: Requirements 2.3
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    metric=st.sampled_from(METRIC_NAMES),
    invalid_val=invalid_threshold_values,
    env_val=valid_positive_floats,
)
def test_property_4_invalid_tag_falls_back_to_env(metric, invalid_val, env_val):
    """Feature: aws-monitoring-engine, Property 4: 잘못된 임계치 태그 무효 처리"""
    tags = {f"Threshold_{metric}": invalid_val}
    env_key = f"DEFAULT_{metric.upper()}_THRESHOLD"

    with patch.dict(os.environ, {env_key: str(env_val)}, clear=False):
        result = get_threshold(tags, metric)

    assert result == pytest.approx(env_val), (
        f"무효 태그 {invalid_val!r} 시 환경변수 {env_val}로 폴백해야 함, 실제: {result}"
    )


# ──────────────────────────────────────────────
# Property 13: Tag_Resolver 절대 유효값 반환 보장
# Validates: Requirements 2.5
# ──────────────────────────────────────────────

@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    metric=st.sampled_from(METRIC_NAMES),
    tags=st.dictionaries(st.text(), st.text()),
    # 환경변수 값은 null 문자 제외 (OS 환경변수 제약)
    env_val=st.one_of(st.none(), st.text().filter(lambda s: "\x00" not in s)),
)
def test_property_13_always_returns_positive_float(metric, tags, env_val):
    """Feature: aws-monitoring-engine, Property 13: Tag_Resolver 절대 유효값 반환 보장"""
    env_key = f"DEFAULT_{metric.upper()}_THRESHOLD"
    env_patch = {env_key: env_val} if env_val is not None else {}

    with patch.dict(os.environ, env_patch, clear=False):
        if env_val is None and env_key in os.environ:
            del os.environ[env_key]
        try:
            result = get_threshold(tags, metric)
        except Exception as e:
            pytest.fail(f"get_threshold가 예외를 발생시켜서는 안 됨: {e}")

    assert result is not None, "None을 반환해서는 안 됨"
    assert isinstance(result, float), f"float을 반환해야 함, 실제: {type(result)}"
    assert result > 0, f"양의 숫자(> 0)를 반환해야 함, 실제: {result}"


# ──────────────────────────────────────────────
# 단위 테스트 - Requirements 2.1, 2.2, 2.3, 2.5
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# is_threshold_off() 단위 테스트
# Requirements: 8.1, 8.2, 8.3
# ──────────────────────────────────────────────

class TestIsThresholdOff:
    """is_threshold_off() 단위 테스트"""

    def test_off_lowercase_returns_true(self):
        """'off' → True"""
        assert is_threshold_off({"Threshold_CPU": "off"}, "CPU") is True

    def test_off_uppercase_returns_true(self):
        """'OFF' → True"""
        assert is_threshold_off({"Threshold_CPU": "OFF"}, "CPU") is True

    def test_off_mixed_case_off_returns_true(self):
        """'Off' → True"""
        assert is_threshold_off({"Threshold_CPU": "Off"}, "CPU") is True

    def test_off_mixed_case_oFf_returns_true(self):
        """'oFf' → True"""
        assert is_threshold_off({"Threshold_CPU": "oFf"}, "CPU") is True

    def test_off_with_whitespace_returns_true(self):
        """' off ' (앞뒤 공백) → True"""
        assert is_threshold_off({"Threshold_CPU": " off "}, "CPU") is True

    def test_positive_number_returns_false(self):
        """양의 숫자 문자열 → False"""
        assert is_threshold_off({"Threshold_CPU": "90"}, "CPU") is False

    def test_empty_string_returns_false(self):
        """빈 문자열 → False"""
        assert is_threshold_off({"Threshold_CPU": ""}, "CPU") is False

    def test_tag_not_set_returns_false(self):
        """태그 미설정 → False"""
        assert is_threshold_off({}, "CPU") is False

    def test_disk_metric_off(self):
        """Disk 계열 메트릭 off 체크"""
        assert is_threshold_off({"Threshold_Disk_root": "off"}, "Disk_root") is True

    def test_different_metric_not_affected(self):
        """다른 메트릭의 off 태그는 영향 없음"""
        assert is_threshold_off({"Threshold_Memory": "off"}, "CPU") is False


class TestGetThresholdUnit:
    """get_threshold 구체적 예시 및 엣지 케이스"""

    def test_tag_cpu_90_returns_90(self):
        """CPU 태그 90 → 90.0 반환"""
        assert get_threshold({"Threshold_CPU": "90"}, "CPU") == 90.0

    def test_tag_memory_float(self):
        """Memory 태그 실수 → 그대로 반환"""
        assert get_threshold({"Threshold_Memory": "75.5"}, "Memory") == pytest.approx(75.5)

    def test_no_tag_uses_env_var(self, monkeypatch):
        """태그 없음 + 환경변수 70 → 70.0 반환"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "70")
        assert get_threshold({}, "CPU") == pytest.approx(70.0)

    def test_invalid_tag_abc_falls_back_to_env(self, monkeypatch):
        """태그 'abc' → 환경변수 폴백"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "75")
        assert get_threshold({"Threshold_CPU": "abc"}, "CPU") == pytest.approx(75.0)

    def test_invalid_tag_negative_falls_back_to_env(self, monkeypatch):
        """태그 '-5' → 환경변수 폴백"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "75")
        assert get_threshold({"Threshold_CPU": "-5"}, "CPU") == pytest.approx(75.0)

    def test_invalid_tag_zero_falls_back_to_env(self, monkeypatch):
        """태그 '0' → 환경변수 폴백"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "75")
        assert get_threshold({"Threshold_CPU": "0"}, "CPU") == pytest.approx(75.0)

    def test_invalid_tag_empty_falls_back_to_env(self, monkeypatch):
        """태그 '' → 환경변수 폴백"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "75")
        assert get_threshold({"Threshold_CPU": ""}, "CPU") == pytest.approx(75.0)

    def test_no_tag_no_env_uses_hardcoded_cpu(self, monkeypatch):
        """태그 없음 + 환경변수 없음 → CPU 하드코딩 기본값 80"""
        monkeypatch.delenv("DEFAULT_CPU_THRESHOLD", raising=False)
        assert get_threshold({}, "CPU") == HARDCODED_DEFAULTS["CPU"]

    def test_no_tag_no_env_uses_hardcoded_memory(self, monkeypatch):
        """태그 없음 + 환경변수 없음 → Memory 하드코딩 기본값 80"""
        monkeypatch.delenv("DEFAULT_MEMORY_THRESHOLD", raising=False)
        assert get_threshold({}, "Memory") == HARDCODED_DEFAULTS["Memory"]

    def test_no_tag_no_env_uses_hardcoded_connections(self, monkeypatch):
        """태그 없음 + 환경변수 없음 → Connections 하드코딩 기본값 100"""
        monkeypatch.delenv("DEFAULT_CONNECTIONS_THRESHOLD", raising=False)
        assert get_threshold({}, "Connections") == HARDCODED_DEFAULTS["Connections"]

    def test_invalid_env_var_falls_back_to_hardcoded(self, monkeypatch):
        """환경변수도 무효('abc') → 하드코딩 기본값"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "abc")
        assert get_threshold({}, "CPU") == HARDCODED_DEFAULTS["CPU"]

    def test_invalid_env_var_negative_falls_back_to_hardcoded(self, monkeypatch):
        """환경변수도 음수('-10') → 하드코딩 기본값"""
        monkeypatch.setenv("DEFAULT_CPU_THRESHOLD", "-10")
        assert get_threshold({}, "CPU") == HARDCODED_DEFAULTS["CPU"]


class TestHasMonitoringTag:
    """has_monitoring_tag 단위 테스트"""

    def test_monitoring_on_returns_true(self):
        assert has_monitoring_tag({"Monitoring": "on"}) is True

    def test_monitoring_on_case_insensitive(self):
        assert has_monitoring_tag({"Monitoring": "ON"}) is True
        assert has_monitoring_tag({"Monitoring": "On"}) is True

    def test_monitoring_off_returns_false(self):
        assert has_monitoring_tag({"Monitoring": "off"}) is False

    def test_no_monitoring_tag_returns_false(self):
        assert has_monitoring_tag({}) is False
        assert has_monitoring_tag({"Name": "test"}) is False

    def test_monitoring_other_value_returns_false(self):
        assert has_monitoring_tag({"Monitoring": "yes"}) is False
        assert has_monitoring_tag({"Monitoring": "true"}) is False


# ──────────────────────────────────────────────
# Disk 경로 인코딩/역변환 및 get_disk_thresholds 단위 테스트
# ──────────────────────────────────────────────

from common.tag_resolver import get_disk_thresholds, disk_path_to_tag_suffix, tag_suffix_to_disk_path


class TestDiskPathEncoding:
    """disk_path_to_tag_suffix / tag_suffix_to_disk_path 단위 테스트"""

    def test_root_path_to_suffix(self):
        assert disk_path_to_tag_suffix("/") == "root"

    def test_data_path_to_suffix(self):
        assert disk_path_to_tag_suffix("/data") == "data"

    def test_app_path_to_suffix(self):
        assert disk_path_to_tag_suffix("/app") == "app"

    def test_nested_path_to_suffix(self):
        assert disk_path_to_tag_suffix("/var/log") == "var_log"

    def test_root_suffix_to_path(self):
        assert tag_suffix_to_disk_path("root") == "/"

    def test_data_suffix_to_path(self):
        assert tag_suffix_to_disk_path("data") == "/data"

    def test_app_suffix_to_path(self):
        assert tag_suffix_to_disk_path("app") == "/app"

    def test_var_log_suffix_to_path(self):
        assert tag_suffix_to_disk_path("var_log") == "/var_log"


class TestGetDiskThresholds:
    """get_disk_thresholds 단위 테스트"""

    def test_single_disk_tag(self):
        tags = {"Threshold_Disk_root": "85", "Monitoring": "on"}
        result = get_disk_thresholds(tags)
        assert result == {"/": 85.0}

    def test_multiple_disk_tags(self):
        tags = {
            "Threshold_Disk_root": "85",
            "Threshold_Disk_data": "90",
            "Threshold_Disk_app": "80",
        }
        result = get_disk_thresholds(tags)
        assert result == {"/": 85.0, "/data": 90.0, "/app": 80.0}

    def test_no_disk_tags_returns_empty(self):
        tags = {"Threshold_CPU": "90", "Monitoring": "on"}
        assert get_disk_thresholds(tags) == {}

    def test_invalid_disk_tag_skipped(self):
        tags = {"Threshold_Disk_root": "abc", "Threshold_Disk_data": "90"}
        result = get_disk_thresholds(tags)
        assert result == {"/data": 90.0}

    def test_zero_disk_tag_skipped(self):
        tags = {"Threshold_Disk_root": "0", "Threshold_Disk_data": "90"}
        result = get_disk_thresholds(tags)
        assert result == {"/data": 90.0}

    def test_negative_disk_tag_skipped(self):
        tags = {"Threshold_Disk_root": "-5"}
        assert get_disk_thresholds(tags) == {}


class TestGetThresholdDiskMetric:
    """get_threshold의 Disk 계열 메트릭 처리 테스트"""

    def test_disk_root_tag(self):
        assert get_threshold({"Threshold_Disk_root": "85"}, "Disk_root") == 85.0

    def test_disk_data_tag(self):
        assert get_threshold({"Threshold_Disk_data": "90"}, "Disk_data") == 90.0

    def test_disk_falls_back_to_disk_env(self, monkeypatch):
        """Disk_root 태그 없을 때 DEFAULT_DISK_THRESHOLD 환경변수 사용"""
        monkeypatch.setenv("DEFAULT_DISK_THRESHOLD", "75")
        assert get_threshold({}, "Disk_root") == pytest.approx(75.0)

    def test_disk_falls_back_to_hardcoded(self, monkeypatch):
        """태그/환경변수 모두 없을 때 HARDCODED_DEFAULTS['Disk'] 사용"""
        monkeypatch.delenv("DEFAULT_DISK_THRESHOLD", raising=False)
        assert get_threshold({}, "Disk_root") == HARDCODED_DEFAULTS["Disk"]

    def test_new_metrics_have_hardcoded_defaults(self, monkeypatch):
        """신규 메트릭들의 하드코딩 기본값 확인"""
        for metric in ["FreeMemoryGB", "FreeStorageGB", "RequestCount", "HealthyHostCount"]:
            monkeypatch.delenv(f"DEFAULT_{metric.upper()}_THRESHOLD", raising=False)
            result = get_threshold({}, metric)
            assert result == HARDCODED_DEFAULTS[metric]


# ──────────────────────────────────────────────
# get_resource_tags ALB/NLB 호환
# ──────────────────────────────────────────────

class TestGetResourceTags:
    """get_resource_tags()가 ALB/NLB 타입도 _get_elbv2_tags()를 호출하는지 검증."""

    def test_alb_calls_elbv2_tags(self):
        from common.tag_resolver import get_resource_tags
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.tag_resolver._get_elbv2_tags", return_value={"Monitoring": "on"}) as mock:
            result = get_resource_tags(alb_arn, "ALB")
        mock.assert_called_once_with(alb_arn)
        assert result == {"Monitoring": "on"}

    def test_nlb_calls_elbv2_tags(self):
        from common.tag_resolver import get_resource_tags
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        with patch("common.tag_resolver._get_elbv2_tags", return_value={"Name": "my-nlb"}) as mock:
            result = get_resource_tags(nlb_arn, "NLB")
        mock.assert_called_once_with(nlb_arn)
        assert result == {"Name": "my-nlb"}

    def test_elb_still_calls_elbv2_tags(self):
        """기존 ELB 타입도 여전히 동작하는지 확인."""
        from common.tag_resolver import get_resource_tags
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/old/xyz"
        with patch("common.tag_resolver._get_elbv2_tags", return_value={}) as mock:
            result = get_resource_tags(arn, "ELB")
        mock.assert_called_once_with(arn)
        assert result == {}
