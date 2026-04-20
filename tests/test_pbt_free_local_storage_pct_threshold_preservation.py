"""
Preservation Property Test - FreeLocalStorageGB 수정 시 기존 동작 보존

Property 2 (Preservation): 기존 FreeMemoryGB 퍼센트 로직, Serverless v2 동작,
GB 절대값 태그 오버라이드, 일반 RDS 동작, 기타 메트릭 동작이 수정 후에도
동일하게 유지되는지 검증한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

EXPECTED: These tests PASS on unfixed code (existing behavior is correct).
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_manager import (
    _resolve_free_memory_threshold,
    _get_aurora_alarm_defs,
    _get_alarm_defs,
)
from common.tag_resolver import get_threshold, is_threshold_off
from common import HARDCODED_DEFAULTS
from common.collectors.rds import _INSTANCE_CLASS_MEMORY_MAP

_BYTES_PER_GB = 1073741824  # 1024**3

# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

mapped_instance_class = st.sampled_from(list(_INSTANCE_CLASS_MEMORY_MAP.keys()))
valid_pct = st.floats(min_value=1.0, max_value=99.0, allow_nan=False, allow_infinity=False)
valid_gb = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)
other_metrics = st.sampled_from(["CPU", "Connections", "ReadLatency", "WriteLatency"])


# ──────────────────────────────────────────────
# Property 2a: _resolve_free_memory_threshold() 결과 불변
# Validates: Requirements 3.4
# ──────────────────────────────────────────────

class TestPreservationFreeMemoryThreshold:
    """_resolve_free_memory_threshold() 결과가 수정 전후 동일한지 검증."""

    @given(instance_class=mapped_instance_class, pct=valid_pct)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_free_memory_threshold_with_pct_tag(self, instance_class, pct):
        """
        **Validates: Requirements 3.4**

        _resolve_free_memory_threshold() with Threshold_FreeMemoryPct tag
        produces percent-based threshold unchanged.
        """
        total_mem = _INSTANCE_CLASS_MEMORY_MAP[instance_class]
        tags = {
            "Threshold_FreeMemoryPct": str(pct),
            "_total_memory_bytes": str(total_mem),
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        expected_cw = (pct / 100) * total_mem
        expected_display = round(expected_cw / _BYTES_PER_GB, 2)
        assert cw_bytes == expected_cw
        assert display_gb == expected_display

    @given(instance_class=mapped_instance_class)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_free_memory_threshold_default_pct(self, instance_class):
        """
        **Validates: Requirements 3.4**

        _resolve_free_memory_threshold() with _total_memory_bytes only
        uses default 20% unchanged.
        """
        total_mem = _INSTANCE_CLASS_MEMORY_MAP[instance_class]
        tags = {"_total_memory_bytes": str(total_mem)}
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        default_pct = HARDCODED_DEFAULTS.get("FreeMemoryPct", 20.0)
        expected_cw = (default_pct / 100) * total_mem
        expected_display = round(expected_cw / _BYTES_PER_GB, 2)
        assert cw_bytes == expected_cw
        assert display_gb == expected_display


# ──────────────────────────────────────────────
# Property 2b: Serverless v2 → FreeLocalStorageGB 알람 미포함
# Validates: Requirements 3.2
# ──────────────────────────────────────────────

class TestPreservationServerlessV2NoFreeLocalStorage:
    """Serverless v2 인스턴스에서 _get_aurora_alarm_defs() 결과에
    FreeLocalStorageGB 알람이 포함되지 않는지 검증."""

    @given(max_acu=st.floats(min_value=1.0, max_value=256.0,
                              allow_nan=False, allow_infinity=False))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_serverless_v2_excludes_free_local_storage(self, max_acu):
        """
        **Validates: Requirements 3.2**

        Serverless v2 instances must NOT include FreeLocalStorageGB alarm.
        """
        tags = {
            "_is_serverless_v2": "true",
            "_is_cluster_writer": "true",
            "_has_readers": "false",
            "_max_acu": str(max_acu),
        }
        alarm_defs = _get_aurora_alarm_defs(tags)
        metrics = {d["metric"] for d in alarm_defs}

        assert "FreeLocalStorageGB" not in metrics, (
            f"Serverless v2 should NOT include FreeLocalStorageGB. "
            f"Got metrics: {metrics}"
        )


# ──────────────────────────────────────────────
# Property 2c: Threshold_FreeLocalStorageGB 태그 → GB 절대값
# Validates: Requirements 3.1
# ──────────────────────────────────────────────

class TestPreservationFreeLocalStorageGBTag:
    """Threshold_FreeLocalStorageGB 태그가 명시적으로 설정된 경우
    get_threshold()가 GB 절대값을 반환하는지 검증."""

    @given(gb=valid_gb)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_explicit_gb_tag_returns_absolute_value(self, gb):
        """
        **Validates: Requirements 3.1**

        Threshold_FreeLocalStorageGB tag → get_threshold returns GB absolute value.
        """
        tags = {"Threshold_FreeLocalStorageGB": str(gb)}
        result = get_threshold(tags, "FreeLocalStorageGB")
        assert result == gb, (
            f"Expected get_threshold to return {gb}, got {result}"
        )

    def test_off_tag_disables_alarm(self):
        """
        **Validates: Requirements 3.6**

        Threshold_FreeLocalStorageGB=off → is_threshold_off returns True.
        """
        tags = {"Threshold_FreeLocalStorageGB": "off"}
        assert is_threshold_off(tags, "FreeLocalStorageGB") is True


# ──────────────────────────────────────────────
# Property 2d: 일반 RDS → FreeLocalStorageGB 알람 미포함
# Validates: Requirements 3.5
# ──────────────────────────────────────────────

class TestPreservationRDSNoFreeLocalStorage:
    """일반 RDS(비Aurora) 인스턴스에서 _get_alarm_defs("RDS") 결과에
    FreeLocalStorageGB 알람이 포함되지 않는지 검증."""

    def test_rds_excludes_free_local_storage(self):
        """
        **Validates: Requirements 3.5**

        Regular RDS must NOT include FreeLocalStorageGB alarm.
        """
        alarm_defs = _get_alarm_defs("RDS")
        metrics = {d["metric"] for d in alarm_defs}

        assert "FreeLocalStorageGB" not in metrics, (
            f"Regular RDS should NOT include FreeLocalStorageGB. "
            f"Got metrics: {metrics}"
        )


# ──────────────────────────────────────────────
# Property 2e: 기타 메트릭(CPU, Connections 등) 동작 불변
# Validates: Requirements 3.3
# ──────────────────────────────────────────────

class TestPreservationOtherMetrics:
    """FreeLocalStorageGB 이외 메트릭의 get_threshold() 동작이 불변인지 검증."""

    @given(metric=other_metrics)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_other_metrics_use_hardcoded_defaults(self, metric):
        """
        **Validates: Requirements 3.3**

        Other metrics (CPU, Connections, etc.) use HARDCODED_DEFAULTS unchanged.
        """
        tags: dict = {}
        result = get_threshold(tags, metric)
        expected = HARDCODED_DEFAULTS[metric]
        assert result == expected, (
            f"get_threshold({{}}, '{metric}') = {result}, "
            f"expected HARDCODED_DEFAULTS['{metric}'] = {expected}"
        )
