"""
Property-Based Tests for expand-alb-rds-metrics feature.

ALB(ELB4XX, TargetConnectionError) 및 RDS(ConnectionAttempts) 메트릭 확장에 대한
Hypothesis PBT 검증.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from common import HARDCODED_DEFAULTS
from common.alarm_manager import (
    _build_dimensions,
    _get_alarm_defs,
    _HARDCODED_METRIC_KEYS,
    _metric_name_to_key,
    _parse_threshold_tags,
)
from common.tag_resolver import get_threshold


# ──────────────────────────────────────────────
# 기대 메트릭 키 집합
# ──────────────────────────────────────────────

_EXPECTED_METRIC_KEYS = {
    "ALB": {
        "RequestCount", "ELB5XX", "TargetResponseTime",
        "ELB4XX", "TargetConnectionError",
    },
    "RDS": {
        "CPU", "FreeMemoryGB", "FreeStorageGB",
        "Connections", "ReadLatency", "WriteLatency",
        "ConnectionAttempts",
    },
}

_REQUIRED_FIELDS = {"namespace", "metric_name", "dimension_key", "stat", "comparison"}

# 새 하드코딩 메트릭 키 (Property 3 대상)
_NEW_HARDCODED_KEYS = ["ELB4XX", "TargetConnectionError", "ConnectionAttempts"]


# ──────────────────────────────────────────────
# Property 1: 알람 정의 완전성 (Alarm Definition Completeness)
# Feature: expand-alb-rds-metrics, Property 1: 알람 정의 완전성
# ──────────────────────────────────────────────

class TestAlarmDefinitionCompleteness:
    """
    **Validates: Requirements 1.1, 2.1, 3.1, 6.1**
    """

    @given(resource_type=st.sampled_from(["ALB", "RDS"]))
    @settings(max_examples=100)
    def test_alarm_defs_contain_expected_metrics(self, resource_type: str):
        # Feature: expand-alb-rds-metrics, Property 1: 알람 정의 완전성
        # **Validates: Requirements 1.1, 2.1, 3.1, 6.1**
        alarm_defs = _get_alarm_defs(resource_type)
        actual_keys = {d["metric"] for d in alarm_defs}
        expected_keys = _EXPECTED_METRIC_KEYS[resource_type]

        assert actual_keys >= expected_keys, (
            f"{resource_type}: missing metrics "
            f"{expected_keys - actual_keys}"
        )

        for alarm_def in alarm_defs:
            missing = _REQUIRED_FIELDS - alarm_def.keys()
            assert not missing, (
                f"{resource_type}/{alarm_def.get('metric')}: "
                f"missing fields {missing}"
            )


# ──────────────────────────────────────────────
# Property 2: ALB LB 레벨 메트릭 단일 디멘션
# Feature: expand-alb-rds-metrics, Property 2: ALB LB 레벨 단일 디멘션
# ──────────────────────────────────────────────

# ARN suffix 전략: 알파벳+숫자 1~20자
_arn_suffix = st.from_regex(r"[a-z0-9]{1,20}", fullmatch=True)


class TestALBLBLevelSingleDimension:
    """
    **Validates: Requirements 1.2, 2.2, 6.2**
    """

    @given(suffix=_arn_suffix)
    @settings(max_examples=100)
    def test_lb_level_metrics_use_single_loadbalancer_dimension(
        self, suffix: str,
    ):
        # Feature: expand-alb-rds-metrics, Property 2: ALB LB 레벨 단일 디멘션
        # **Validates: Requirements 1.2, 2.2, 6.2**
        alb_arn = (
            f"arn:aws:elasticloadbalancing:us-east-1:123456789012:"
            f"loadbalancer/app/my-alb/{suffix}"
        )
        alarm_defs = _get_alarm_defs("ALB")
        lb_level_defs = [
            d for d in alarm_defs if d["dimension_key"] == "LoadBalancer"
        ]

        # ELB4XX, TargetConnectionError 포함 확인
        lb_metrics = {d["metric"] for d in lb_level_defs}
        assert "ELB4XX" in lb_metrics
        assert "TargetConnectionError" in lb_metrics

        for alarm_def in lb_level_defs:
            dims = _build_dimensions(alarm_def, alb_arn, "ALB", {})
            dim_names = [d["Name"] for d in dims]

            assert dim_names == ["LoadBalancer"], (
                f"metric={alarm_def['metric']}: "
                f"expected ['LoadBalancer'], got {dim_names}"
            )
            assert not any(d["Name"] == "TargetGroup" for d in dims), (
                f"metric={alarm_def['metric']}: "
                f"TargetGroup dimension must not be present"
            )


# ──────────────────────────────────────────────
# Property 3: 태그 임계치 오버라이드
# Feature: expand-alb-rds-metrics, Property 3: 태그 임계치 오버라이드
# ──────────────────────────────────────────────

class TestTagThresholdOverride:
    """
    **Validates: Requirements 4.1**
    """

    @given(
        metric_key=st.sampled_from(_NEW_HARDCODED_KEYS),
        threshold=st.floats(
            min_value=0.01, max_value=99999.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_tag_overrides_hardcoded_default(
        self, metric_key: str, threshold: float,
    ):
        # Feature: expand-alb-rds-metrics, Property 3: 태그 임계치 오버라이드
        # **Validates: Requirements 4.1**
        tags = {f"Threshold_{metric_key}": str(threshold)}
        result = get_threshold(tags, metric_key)

        assert result == threshold, (
            f"metric={metric_key}: expected {threshold}, "
            f"got {result} (default={HARDCODED_DEFAULTS.get(metric_key)})"
        )


# ──────────────────────────────────────────────
# Property 4: 동적 태그 하드코딩 키 제외
# Feature: expand-alb-rds-metrics, Property 4: 동적 태그 하드코딩 키 제외
# ──────────────────────────────────────────────

# 비하드코딩 동적 메트릭 키 (태그 허용 문자만 사용)
_dynamic_metric_keys = st.from_regex(r"[A-Z][a-zA-Z0-9]{2,15}", fullmatch=True).filter(
    lambda k: k not in _HARDCODED_METRIC_KEYS.get("ALB", set())
    and k not in _HARDCODED_METRIC_KEYS.get("RDS", set())
    and not k.startswith("Disk")
    and not k.startswith("LT_")
    and k != "FreeMemoryPct"
)


class TestDynamicTagHardcodedKeyExclusion:
    """
    **Validates: Requirements 4.2**
    """

    @given(
        resource_type=st.sampled_from(["ALB", "RDS"]),
        dynamic_keys=st.lists(
            _dynamic_metric_keys, min_size=1, max_size=3, unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_hardcoded_keys_excluded_from_dynamic_result(
        self, resource_type: str, dynamic_keys: list[str],
    ):
        # Feature: expand-alb-rds-metrics, Property 4: 동적 태그 하드코딩 키 제외
        # **Validates: Requirements 4.2**
        hardcoded = _HARDCODED_METRIC_KEYS[resource_type]
        tags: dict[str, str] = {"Monitoring": "on"}

        # 하드코딩 키에 대한 Threshold_ 태그 추가
        for hk in hardcoded:
            if hk == "Disk":
                continue
            tags[f"Threshold_{hk}"] = "42"

        # 비하드코딩 동적 키에 대한 Threshold_ 태그 추가
        for dk in dynamic_keys:
            tags[f"Threshold_{dk}"] = "99"

        result = _parse_threshold_tags(tags, resource_type)

        # 하드코딩 키가 결과에 포함되지 않아야 함
        for hk in hardcoded:
            assert hk not in result, (
                f"{resource_type}: hardcoded key '{hk}' "
                f"found in dynamic result {result}"
            )

        # 비하드코딩 키만 결과에 포함되어야 함
        for dk in dynamic_keys:
            assert dk in result, (
                f"{resource_type}: dynamic key '{dk}' "
                f"missing from result {result}"
            )
