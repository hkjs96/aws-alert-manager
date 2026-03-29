"""
Property 6: 태그 키/값 유효성 검증

_parse_threshold_tags()가 유효하지 않은 태그를 skip하고
유효한 태그만 반환하는지 검증.

유효하지 않은 태그: 빈 메트릭 이름, 128자 초과 키, 비숫자 값, 0 이하 값
유효한 태그: 양의 숫자 값, 128자 이하 키, 하드코딩 목록에 없는 메트릭

**Validates: AWS 태그 제약 사항**
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.alarm_manager import _parse_threshold_tags
from common.alarm_registry import _get_alarm_defs


# ──────────────────────────────────────────────
# 레지스트리 기반 동적 메트릭 정의
# ──────────────────────────────────────────────

_HARDCODED_METRICS = {
    rt: {d["metric"] for d in _get_alarm_defs(rt)}
    for rt in ["EC2", "RDS", "ALB", "NLB", "TG"]
}

# AWS 태그 허용 문자 (메트릭 이름 부분)
_TAG_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " _.:/=+-@"
)

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])


# ──────────────────────────────────────────────
# 유효한 동적 메트릭 태그 전략
# ──────────────────────────────────────────────

# 유효한 메트릭 이름: 1~118자, 태그 허용 문자만
valid_metric_names = st.text(
    alphabet=st.sampled_from(sorted(_TAG_ALLOWED_CHARS)),
    min_size=1,
    max_size=118,
)

# 양의 숫자 값
positive_values = st.floats(
    min_value=0.01,
    max_value=99999.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda x: str(round(x, 2)))


@st.composite
def valid_dynamic_tags(draw):
    """유효한 동적 메트릭 태그 1~5개 생성."""
    rtype = draw(resource_types)
    hardcoded = _HARDCODED_METRICS[rtype]
    n_tags = draw(st.integers(min_value=1, max_value=5))

    tags = {"Monitoring": "on", "Name": "test-resource"}
    metrics = {}
    for _ in range(n_tags):
        name = draw(valid_metric_names)
        # 하드코딩 목록과 Disk_ 접두사 제외
        assume(name not in hardcoded)
        assume(not name.startswith("Disk_"))
        value = draw(positive_values)
        tag_key = f"Threshold_{name}"
        # 태그 키 128자 이하
        assume(len(tag_key) <= 128)
        tags[tag_key] = value
        metrics[name] = float(value)

    return rtype, tags, metrics


# ──────────────────────────────────────────────
# 유효하지 않은 태그 전략
# ──────────────────────────────────────────────

# 빈 메트릭 이름
empty_metric_tags = st.fixed_dictionaries({
    "Monitoring": st.just("on"),
    "Threshold_": st.just("100"),
})

# 비숫자 값
non_numeric_values = st.one_of(
    st.just("abc"),
    st.just(""),
    st.just("not-a-number"),
    st.just("12.34.56"),
    st.just("NaN"),
    st.just("inf"),
)

# 0 이하 값
non_positive_values = st.one_of(
    st.just("0"),
    st.just("-1"),
    st.just("-0.5"),
    st.just("-100"),
)


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestTagValidation:
    """
    _parse_threshold_tags()의 태그 키/값 유효성 검증.

    **Validates: AWS 태그 제약 사항**
    """

    @given(data=valid_dynamic_tags())
    @settings(max_examples=20, deadline=None)
    def test_valid_tags_are_included(self, data):
        """
        **Property 6: 유효한 태그 포함** - 유효한 동적 태그는 결과에 포함

        양의 숫자 값, 128자 이하 키, 하드코딩 목록에 없는 메트릭 이름을 가진
        태그는 _parse_threshold_tags() 결과에 포함되어야 한다.

        **Validates: AWS 태그 제약 사항**
        """
        rtype, tags, expected_metrics = data

        result = _parse_threshold_tags(tags, rtype)

        for metric_name, expected_val in expected_metrics.items():
            assert metric_name in result, (
                f"Valid metric '{metric_name}' not found in result.\n"
                f"tags={tags}\n"
                f"result={result}"
            )
            actual_val, actual_comp = result[metric_name]
            assert abs(actual_val - expected_val) < 0.01, (
                f"Threshold mismatch for '{metric_name}': "
                f"expected={expected_val}, actual={actual_val}"
            )
            assert actual_comp == "GreaterThanThreshold", (
                f"Comparison mismatch for '{metric_name}': "
                f"expected='GreaterThanThreshold', actual={actual_comp!r}"
            )

    @given(resource_type=resource_types, value=non_numeric_values)
    @settings(max_examples=20, deadline=None)
    def test_non_numeric_values_are_skipped(self, resource_type, value):
        """
        **Property 6: 비숫자 값 skip** - 숫자로 파싱 불가능한 값은 skip

        **Validates: AWS 태그 제약 사항**
        """
        tags = {
            "Monitoring": "on",
            "Threshold_NetworkIn": value,
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert "NetworkIn" not in result, (
            f"Non-numeric value '{value}' should be skipped, "
            f"but NetworkIn found in result: {result}"
        )

    @given(resource_type=resource_types, value=non_positive_values)
    @settings(max_examples=20, deadline=None)
    def test_non_positive_values_are_skipped(self, resource_type, value):
        """
        **Property 6: 0 이하 값 skip** - 0 또는 음수 값은 skip

        **Validates: AWS 태그 제약 사항**
        """
        tags = {
            "Monitoring": "on",
            "Threshold_NetworkIn": value,
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert "NetworkIn" not in result, (
            f"Non-positive value '{value}' should be skipped, "
            f"but NetworkIn found in result: {result}"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_empty_metric_name_is_skipped(self, resource_type):
        """
        **Property 6: 빈 메트릭 이름 skip** - Threshold_ 뒤에 이름이 없으면 skip

        **Validates: AWS 태그 제약 사항**
        """
        tags = {
            "Monitoring": "on",
            "Threshold_": "100",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert len(result) == 0, (
            f"Empty metric name should be skipped, but got: {result}"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_key_exceeding_128_chars_is_skipped(self, resource_type):
        """
        **Property 6: 128자 초과 키 skip** - 태그 키가 128자를 초과하면 skip

        **Validates: AWS 태그 제약 사항**
        """
        # Threshold_ (10자) + 119자 메트릭 이름 = 129자 > 128자
        long_metric = "A" * 119
        tag_key = f"Threshold_{long_metric}"
        assert len(tag_key) == 129  # sanity check

        tags = {
            "Monitoring": "on",
            tag_key: "100",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert long_metric not in result, (
            f"Tag key exceeding 128 chars should be skipped, "
            f"but {long_metric!r} found in result"
        )

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_hardcoded_metrics_are_excluded(self, resource_type):
        """
        **Property 6: 하드코딩 메트릭 제외** - 하드코딩 목록의 메트릭은 동적 결과에서 제외

        **Validates: AWS 태그 제약 사항**
        """
        hardcoded = _HARDCODED_METRICS[resource_type]
        tags = {"Monitoring": "on"}
        for metric in hardcoded:
            if metric == "Disk":
                continue  # Disk_* 패턴은 별도 처리
            tags[f"Threshold_{metric}"] = "100"

        result = _parse_threshold_tags(tags, resource_type)

        for metric in hardcoded:
            if metric == "Disk":
                continue
            assert metric not in result, (
                f"Hardcoded metric '{metric}' should be excluded "
                f"from dynamic result: {result}"
            )

    @given(resource_type=resource_types)
    @settings(max_examples=20, deadline=None)
    def test_disk_prefix_tags_are_excluded(self, resource_type):
        """
        **Property 6: Disk_ 접두사 제외** - Threshold_Disk_* 태그는 동적 파싱에서 제외

        **Validates: AWS 태그 제약 사항**
        """
        tags = {
            "Monitoring": "on",
            "Threshold_Disk_root": "85",
            "Threshold_Disk_data": "90",
        }

        result = _parse_threshold_tags(tags, resource_type)

        assert len(result) == 0, (
            f"Threshold_Disk_* tags should be excluded, but got: {result}"
        )
