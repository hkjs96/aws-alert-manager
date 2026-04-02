"""
Property Tests — 기본 알람 정의 확장 (expand-default-alarms)

Property 1: 알람 정의 완전성
Property 2: LB 레벨 단일 디멘션
Property 5: 태그 임계치 오버라이드
Property 6: 동적 태그 하드코딩 키 제외

**Validates: Requirements 1.1-1.8, 2.1-2.7, 3.1-3.6, 4.1-4.7, 5.1-5.10, 6.1-6.3**
"""

import os
from unittest.mock import patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.alarm_registry import _get_alarm_defs, _HARDCODED_METRIC_KEYS
from common.alarm_manager import _parse_threshold_tags
from common.tag_resolver import get_threshold
from common import HARDCODED_DEFAULTS


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])
positive_float = st.floats(min_value=0.1, max_value=1e6, allow_nan=False, allow_infinity=False)

_REQUIRED_FIELDS = {"metric", "stat", "comparison", "period", "namespace",
                    "metric_name", "dimension_key"}


# ──────────────────────────────────────────────
# Property 1: 알람 정의 완전성
# ──────────────────────────────────────────────

@given(rt=resource_types)
@settings(max_examples=20)
def test_alarm_defs_have_all_required_fields(rt):
    """모든 알람 정의에 필수 필드가 존재한다.

    **Validates: Requirements 1.1, 2.1, 3.1, 4.1, 5.1**
    """
    defs = _get_alarm_defs(rt)
    for d in defs:
        missing = _REQUIRED_FIELDS - d.keys()
        assert not missing, f"{rt} alarm {d.get('metric', '?')} missing: {missing}"


@given(rt=resource_types)
@settings(max_examples=20)
def test_alarm_defs_metrics_match_hardcoded_keys(rt):
    """알람 정의 메트릭 집합이 HARDCODED_METRIC_KEYS와 일치.

    **Validates: Requirements 1.2, 2.2, 3.2, 4.2, 5.2**
    """
    defs = _get_alarm_defs(rt)
    actual = {d["metric"] for d in defs}
    expected = _HARDCODED_METRIC_KEYS[rt]
    assert actual == expected, f"{rt}: expected {expected}, got {actual}"


@given(rt=resource_types)
@settings(max_examples=20)
def test_all_metrics_have_hardcoded_defaults(rt):
    """모든 하드코딩 메트릭에 HARDCODED_DEFAULTS 기본값이 존재.

    **Validates: Requirements 3.4, 4.4, 5.4**
    """
    for metric in _HARDCODED_METRIC_KEYS[rt]:
        if metric == "Disk":
            continue  # Disk는 경로별 동적 처리
        assert metric in HARDCODED_DEFAULTS, (
            f"{rt}/{metric} missing from HARDCODED_DEFAULTS"
        )


# ──────────────────────────────────────────────
# Property 2: LB 레벨 단일 디멘션
# ──────────────────────────────────────────────

@given(rt=st.sampled_from(["ALB", "NLB"]))
@settings(max_examples=10)
def test_lb_level_alarms_use_loadbalancer_dimension(rt):
    """ALB/NLB 알람은 LoadBalancer dimension_key를 사용.

    **Validates: Requirements 1.3, 2.3**
    """
    defs = _get_alarm_defs(rt)
    for d in defs:
        assert d["dimension_key"] == "LoadBalancer", (
            f"{rt}/{d['metric']}: expected LoadBalancer, got {d['dimension_key']}"
        )


def test_tg_alarms_use_targetgroup_dimension():
    """TG 알람은 TargetGroup dimension_key를 사용.

    **Validates: Requirements 5.3**
    """
    defs = _get_alarm_defs("TG")
    for d in defs:
        assert d["dimension_key"] == "TargetGroup", (
            f"TG/{d['metric']}: expected TargetGroup, got {d['dimension_key']}"
        )


# ──────────────────────────────────────────────
# Property 5: 태그 임계치 오버라이드
# ──────────────────────────────────────────────

_OVERRIDABLE_METRICS = [
    "CPU", "Connections", "ELB5XX", "TargetResponseTime",
    "ProcessedBytes", "TCPClientReset", "TCPTargetReset",
    "StatusCheckFailed", "ReadLatency", "WriteLatency",
    "RequestCountPerTarget", "TGResponseTime",
    "HealthyHostCount", "UnHealthyHostCount",
]


@given(
    metric=st.sampled_from(_OVERRIDABLE_METRICS),
    val=positive_float,
)
@settings(max_examples=30)
def test_tag_threshold_overrides_default(metric, val):
    """Threshold_{metric} 태그가 기본값을 오버라이드한다.

    **Validates: Requirements 6.1**
    """
    tags = {f"Threshold_{metric}": str(val)}
    result = get_threshold(tags, metric)
    assert result == val, f"Expected {val}, got {result}"


# ──────────────────────────────────────────────
# Property 6: 동적 태그 하드코딩 키 제외
# ──────────────────────────────────────────────

@given(rt=resource_types)
@settings(max_examples=20)
def test_hardcoded_keys_excluded_from_dynamic(rt):
    """하드코딩 메트릭 키는 _parse_threshold_tags 결과에서 제외.

    **Validates: Requirements 6.2**
    """
    hardcoded = _HARDCODED_METRIC_KEYS[rt]
    tags = {"Monitoring": "on"}
    for metric in hardcoded:
        tags[f"Threshold_{metric}"] = "100"
    # 동적 메트릭 1개 추가
    tags["Threshold_CustomMetric"] = "50"

    result = _parse_threshold_tags(tags, rt)

    for metric in hardcoded:
        assert metric not in result, f"{metric} should be excluded from dynamic"
    assert "CustomMetric" in result, "CustomMetric should be in dynamic result"
