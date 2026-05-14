"""
threshold_resolver PBT — Requirements 1.4 (Roadmap Phase 1)

Property 1: 태그 값이 항상 환경 변수/기본값보다 우선
Property 2: multiplier transform 결과 = 원본 × multiplier
Property 3: cw_threshold는 항상 양수
Property 4: display_threshold와 cw_threshold의 관계 단조성
"""

import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


GB = 1073741824

pos_floats = st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False)
pos_ints = st.integers(min_value=1, max_value=1000000).map(float)
thresholds = st.one_of(pos_floats, pos_ints)

tag_threshold = st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False)
env_threshold = st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False)


# ──────────────────────────────────────────────
# Property 1: 태그 값이 환경 변수/기본값보다 우선
# ──────────────────────────────────────────────

class TestTagTakesPriority:
    @given(
        tag_val=tag_threshold,
        env_val=env_threshold,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_태그가_환경변수보다_항상_우선(self, tag_val, env_val):
        """Threshold_CPU 태그가 있으면 환경 변수 DEFAULT_CPU_THRESHOLD보다 항상 우선해야 한다."""
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "CPU"}
        resource_tags = {"Threshold_CPU": str(tag_val)}

        with patch.dict(os.environ, {"DEFAULT_CPU_THRESHOLD": str(env_val)}):
            display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == tag_val, (
            f"태그({tag_val})가 환경변수({env_val})에 밀림: display={display_thr}"
        )

    @given(
        tag_val=tag_threshold,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_FreeMemoryGB_태그가_HARDCODED_DEFAULTS보다_우선(self, tag_val):
        """Threshold_FreeMemoryGB 태그가 HARDCODED_DEFAULTS보다 항상 우선해야 한다."""
        from common.threshold_resolver import resolve_threshold
        from common import HARDCODED_DEFAULTS

        alarm_def = {"metric": "FreeMemoryGB"}
        resource_tags = {"Threshold_FreeMemoryGB": str(tag_val)}

        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        # 기본값이 다르면 태그 값이 반드시 선택되어야 한다
        assert display_thr == tag_val or tag_val == HARDCODED_DEFAULTS.get("FreeMemoryGB")


# ──────────────────────────────────────────────
# Property 2: multiplier transform = 원본 × multiplier
# ──────────────────────────────────────────────

class TestMultiplierTransform:
    @given(
        base_val=thresholds,
        multiplier=st.sampled_from([GB, 1073741824, 1024 * 1024, 1000]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_multiplier_transform_결과가_원본_곱셈과_일치(self, base_val, multiplier):
        """transform_threshold=lambda x: x * multiplier 시 cw_thr == base_val * multiplier."""
        from common.threshold_resolver import resolve_threshold

        alarm_def = {
            "metric": "FreeStorageGB",
            "transform_threshold": lambda x: x * multiplier,
        }
        resource_tags = {"Threshold_FreeStorageGB": str(base_val)}
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        expected_cw = base_val * multiplier
        assert abs(cw_thr - expected_cw) < 1.0, (
            f"cw_thr({cw_thr}) != base_val({base_val}) × multiplier({multiplier}) = {expected_cw}"
        )
        assert display_thr == base_val


# ──────────────────────────────────────────────
# Property 3: cw_threshold는 항상 양수
# ──────────────────────────────────────────────

class TestCwThresholdAlwaysPositive:
    @given(
        pct=st.floats(min_value=1.0, max_value=99.0, allow_nan=False),
        total_gb=st.integers(min_value=1, max_value=2048).map(lambda x: x * GB),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_FreeMemoryGB_cw_threshold_항상_양수(self, pct, total_gb):
        """FreeMemoryGB 임계치 변환 결과가 항상 양수여야 한다."""
        from common.threshold_resolver import _resolve_free_memory_threshold

        resource_tags = {
            "Threshold_FreeMemoryPct": str(pct),
            "_total_memory_bytes": str(total_gb),
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        assert cw_bytes > 0, f"cw_bytes가 0 이하: {cw_bytes}"
        assert display_gb > 0, f"display_gb가 0 이하: {display_gb}"

    @given(
        gb_val=st.floats(min_value=0.1, max_value=10000.0, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_일반_metric_cw_threshold_항상_양수(self, gb_val):
        """일반 metric 임계치도 항상 양수여야 한다."""
        from common.threshold_resolver import resolve_threshold

        alarm_def = {
            "metric": "FreeStorageGB",
            "transform_threshold": lambda x: x * GB,
        }
        resource_tags = {"Threshold_FreeStorageGB": str(gb_val)}
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert cw_thr > 0


# ──────────────────────────────────────────────
# Property 4: FreeMemoryPct 증가 시 cw_bytes 단조 증가
# ──────────────────────────────────────────────

class TestMonotonicity:
    @given(
        pct1=st.floats(min_value=1.0, max_value=49.0, allow_nan=False),
        pct2=st.floats(min_value=50.0, max_value=99.0, allow_nan=False),
        total_gb=st.integers(min_value=4, max_value=512).map(lambda x: x * GB),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_더_높은_FreeMemoryPct는_더_높은_cw_bytes(self, pct1, pct2, total_gb):
        """FreeMemoryPct가 높을수록 CloudWatch 임계치(bytes)도 높아야 한다."""
        from common.threshold_resolver import _resolve_free_memory_threshold

        tags1 = {"Threshold_FreeMemoryPct": str(pct1), "_total_memory_bytes": str(total_gb)}
        tags2 = {"Threshold_FreeMemoryPct": str(pct2), "_total_memory_bytes": str(total_gb)}

        _, cw1 = _resolve_free_memory_threshold(tags1)
        _, cw2 = _resolve_free_memory_threshold(tags2)

        assert cw2 > cw1, (
            f"pct2({pct2}) > pct1({pct1}) 이지만 cw2({cw2}) <= cw1({cw1})"
        )
