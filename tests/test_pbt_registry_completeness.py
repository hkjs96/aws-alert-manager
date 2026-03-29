"""
Property Test — 레지스트리 완전성 (Registry Completeness)

Property 2: ∀ resource_type ∈ SUPPORTED_RESOURCE_TYPES:
  get_alarm_defs(resource_type) 반환 메트릭 집합이 _HARDCODED_METRIC_KEYS와 일치.

리팩터링 후 alarm_registry 모듈이 모든 리소스 타입에 대해
기존과 동일한 메트릭 집합을 반환하는지 검증한다.

**Validates: Requirements 4.1, 6.1, 6.2**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_registry import (
    _get_alarm_defs,
    _HARDCODED_METRIC_KEYS,
    _NAMESPACE_MAP,
    _DIMENSION_KEY_MAP,
)


# 태그 없이 호출 가능한 기본 리소스 타입
_BASIC_RESOURCE_TYPES = ["EC2", "RDS", "ALB", "NLB", "DocDB"]

# TG/AuroraRDS는 태그에 따라 결과가 달라지므로 별도 검증


@given(rt=st.sampled_from(_BASIC_RESOURCE_TYPES))
@settings(max_examples=20)
def test_basic_resource_types_metric_set_matches_hardcoded(rt):
    """기본 리소스 타입의 alarm_defs 메트릭 집합이 HARDCODED_METRIC_KEYS와 일치."""
    defs = _get_alarm_defs(rt)
    actual_metrics = {d["metric"] for d in defs}
    expected_metrics = _HARDCODED_METRIC_KEYS[rt]
    assert actual_metrics == expected_metrics, (
        f"{rt}: expected {expected_metrics}, got {actual_metrics}"
    )


@given(rt=st.sampled_from(_BASIC_RESOURCE_TYPES))
@settings(max_examples=20)
def test_all_resource_types_have_namespace(rt):
    """모든 리소스 타입이 NAMESPACE_MAP에 등록되어 있다."""
    assert rt in _NAMESPACE_MAP, f"{rt} missing from _NAMESPACE_MAP"


@given(rt=st.sampled_from(_BASIC_RESOURCE_TYPES))
@settings(max_examples=20)
def test_all_resource_types_have_dimension_key(rt):
    """모든 리소스 타입이 DIMENSION_KEY_MAP에 등록되어 있다."""
    assert rt in _DIMENSION_KEY_MAP, f"{rt} missing from _DIMENSION_KEY_MAP"


def test_tg_default_metrics():
    """TG 기본(ALB TG) 메트릭 집합이 HARDCODED_METRIC_KEYS와 일치."""
    defs = _get_alarm_defs("TG")
    actual = {d["metric"] for d in defs}
    assert actual == _HARDCODED_METRIC_KEYS["TG"]


def test_tg_nlb_excludes_alb_only_metrics():
    """NLB TG는 RequestCountPerTarget, TGResponseTime을 제외."""
    tags = {"_lb_type": "network"}
    defs = _get_alarm_defs("TG", tags)
    actual = {d["metric"] for d in defs}
    assert "RequestCountPerTarget" not in actual
    assert "TGResponseTime" not in actual
    assert "HealthyHostCount" in actual
    assert "UnHealthyHostCount" in actual


def test_tg_alb_target_type_returns_empty():
    """TargetType=alb인 TG는 빈 알람 목록을 반환."""
    tags = {"_target_type": "alb"}
    defs = _get_alarm_defs("TG", tags)
    assert defs == []


def test_aurora_rds_metrics_include_base():
    """AuroraRDS 기본 메트릭이 HARDCODED_METRIC_KEYS에 포함."""
    tags = {"_is_serverless_v2": "false", "_is_writer": "true"}
    defs = _get_alarm_defs("AuroraRDS", tags)
    actual = {d["metric"] for d in defs}
    # 최소한 CPU, FreeMemoryGB, Connections는 포함
    assert {"CPU", "FreeMemoryGB", "Connections"}.issubset(actual)


def test_unknown_resource_type_returns_empty():
    """알 수 없는 리소스 타입은 빈 리스트를 반환."""
    defs = _get_alarm_defs("Unknown")
    assert defs == []


@given(rt=st.sampled_from(_BASIC_RESOURCE_TYPES))
@settings(max_examples=20)
def test_alarm_defs_have_required_fields(rt):
    """모든 알람 정의에 필수 필드(metric, stat, comparison, period)가 존재."""
    defs = _get_alarm_defs(rt)
    required = {"metric", "stat", "comparison", "period"}
    for d in defs:
        missing = required - d.keys()
        assert not missing, f"{rt} alarm def missing fields: {missing}"
