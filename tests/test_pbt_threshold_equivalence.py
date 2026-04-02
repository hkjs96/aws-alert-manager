"""
Property Test — 임계치 해석 동등성 (Threshold Resolution Equivalence)

Property 3: ∀ alarm_def, resource_tags:
  resolve_threshold(alarm_def, tags) 결과가 개별 분기 로직과 동일.

통합 resolve_threshold()가 FreeMemoryGB, FreeLocalStorageGB, transform_threshold,
일반 메트릭 4가지 경로 모두에서 올바른 결과를 반환하는지 검증한다.

**Validates: Requirements 5.1, 5.6**
"""

import os
from unittest.mock import patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.threshold_resolver import (
    resolve_threshold,
    _resolve_free_memory_threshold,
    _resolve_free_local_storage_threshold,
)
from common.tag_resolver import get_threshold


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

positive_float = st.floats(min_value=0.1, max_value=1e9, allow_nan=False, allow_infinity=False)
pct_float = st.floats(min_value=1.0, max_value=99.0, allow_nan=False, allow_infinity=False)
total_bytes = st.floats(min_value=1073741824, max_value=1e12, allow_nan=False, allow_infinity=False)


# ──────────────────────────────────────────────
# Path 1: 일반 메트릭 (transform 없음)
# ──────────────────────────────────────────────

_SIMPLE_METRICS = ["CPU", "Connections", "ReadLatency", "WriteLatency",
                   "RequestCount", "ELB5XX", "ProcessedBytes",
                   "ActiveFlowCount", "HealthyHostCount"]


@given(
    metric=st.sampled_from(_SIMPLE_METRICS),
    tag_val=positive_float,
)
@settings(max_examples=50)
def test_simple_metric_equals_get_threshold(metric, tag_val):
    """일반 메트릭: resolve_threshold == (get_threshold, get_threshold)."""
    alarm_def = {"metric": metric, "stat": "Average", "comparison": "GreaterThanThreshold", "period": 300}
    tags = {f"Threshold_{metric}": str(tag_val)}

    display, cw = resolve_threshold(alarm_def, tags)
    expected = get_threshold(tags, metric)

    assert display == expected
    assert cw == expected


# ──────────────────────────────────────────────
# Path 2: transform_threshold 있는 메트릭
# ──────────────────────────────────────────────

@given(tag_val=positive_float)
@settings(max_examples=30)
def test_transform_threshold_applied(tag_val):
    """transform_threshold가 있으면 cw_threshold에 적용된다."""
    multiplier = 1073741824  # GB → bytes
    alarm_def = {
        "metric": "FreeStorageGB",
        "stat": "Average",
        "comparison": "LessThanThreshold",
        "period": 300,
        "transform_threshold": lambda x: x * multiplier,
    }
    tags = {"Threshold_FreeStorageGB": str(tag_val)}

    display, cw = resolve_threshold(alarm_def, tags)
    expected_display = get_threshold(tags, "FreeStorageGB")

    assert display == expected_display
    assert cw == expected_display * multiplier


# ──────────────────────────────────────────────
# Path 3: FreeMemoryGB
# ──────────────────────────────────────────────

@given(gb_val=positive_float)
@settings(max_examples=30)
def test_free_memory_gb_fallback(gb_val):
    """FreeMemoryGB GB 절대값 폴백 경로."""
    alarm_def = {"metric": "FreeMemoryGB", "stat": "Average",
                 "comparison": "LessThanThreshold", "period": 300}
    tags = {"Threshold_FreeMemoryGB": str(gb_val)}

    display, cw = resolve_threshold(alarm_def, tags)
    ref_display, ref_cw = _resolve_free_memory_threshold(tags)

    assert display == ref_display
    assert cw == ref_cw


@given(gb_val=positive_float)
@settings(max_examples=30)
def test_free_memory_serverless_uses_gb(gb_val):
    """Serverless v2는 항상 GB 절대값을 사용."""
    alarm_def = {"metric": "FreeMemoryGB", "stat": "Average",
                 "comparison": "LessThanThreshold", "period": 300}
    tags = {
        "Threshold_FreeMemoryGB": str(gb_val),
        "_is_serverless_v2": "true",
    }

    display, cw = resolve_threshold(alarm_def, tags)

    assert display == gb_val
    assert cw == gb_val * 1073741824


@given(pct=pct_float, total=total_bytes)
@settings(max_examples=30)
def test_free_memory_pct_explicit(pct, total):
    """명시적 Threshold_FreeMemoryPct 태그 경로."""
    alarm_def = {"metric": "FreeMemoryGB", "stat": "Average",
                 "comparison": "LessThanThreshold", "period": 300}
    tags = {
        "Threshold_FreeMemoryPct": str(pct),
        "_total_memory_bytes": str(total),
    }

    display, cw = resolve_threshold(alarm_def, tags)
    expected_cw = (pct / 100) * total
    expected_display = round(expected_cw / 1073741824, 2)

    assert display == expected_display
    assert cw == expected_cw


# ──────────────────────────────────────────────
# Path 4: FreeLocalStorageGB
# ──────────────────────────────────────────────

@given(gb_val=positive_float)
@settings(max_examples=30)
def test_free_local_storage_gb_fallback(gb_val):
    """FreeLocalStorageGB GB 절대값 폴백 경로."""
    alarm_def = {"metric": "FreeLocalStorageGB", "stat": "Average",
                 "comparison": "LessThanThreshold", "period": 300}
    tags = {"Threshold_FreeLocalStorageGB": str(gb_val)}

    display, cw = resolve_threshold(alarm_def, tags)
    ref_display, ref_cw = _resolve_free_local_storage_threshold(tags)

    assert display == ref_display
    assert cw == ref_cw


@given(pct=pct_float, total=total_bytes)
@settings(max_examples=30)
def test_free_local_storage_pct_explicit(pct, total):
    """명시적 Threshold_FreeLocalStoragePct 태그 경로."""
    alarm_def = {"metric": "FreeLocalStorageGB", "stat": "Average",
                 "comparison": "LessThanThreshold", "period": 300}
    tags = {
        "Threshold_FreeLocalStoragePct": str(pct),
        "_total_local_storage_bytes": str(total),
    }

    display, cw = resolve_threshold(alarm_def, tags)
    expected_cw = (pct / 100) * total
    expected_display = round(expected_cw / 1073741824, 2)

    assert display == expected_display
    assert cw == expected_cw
