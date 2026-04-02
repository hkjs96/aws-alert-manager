"""
Bug Condition Exploration Test - FreeLocalStorageGB 고정 10GB 임계치 사용 (퍼센트 기반 해석 부재)

Property 1 (Bug Condition): DocDB 및 Aurora RDS Provisioned 인스턴스에서
`_resolve_free_local_storage_threshold()` 함수가 존재하지 않고,
`_total_local_storage_bytes` 태그가 설정되지 않아 모든 인스턴스에
10GB 고정 임계치가 적용되는 버그.

Bug Condition: isBugCondition(input) where
  input.metric == "FreeLocalStorageGB"
  AND input.resource_type IN ["AuroraRDS", "DocDB"]
  AND input.is_serverless == false
  AND NOT hasTag(input.tags, "Threshold_FreeLocalStorageGB")

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5**

EXPECTED: These tests FAIL on unfixed code because _resolve_free_local_storage_threshold()
does not exist yet (ImportError), and _total_local_storage_bytes tag is never set.
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_manager import _resolve_free_local_storage_threshold

_BYTES_PER_GB = 1073741824  # 1024**3

# ──────────────────────────────────────────────
# Strategy: 다양한 로컬 스토리지 용량 (20GB ~ 500GB)
# ──────────────────────────────────────────────

local_storage_gb = st.integers(min_value=20, max_value=500)


# ──────────────────────────────────────────────
# Property 1a: _resolve_free_local_storage_threshold 존재 및 호출 가능
# Validates: Requirements 1.1, 1.4, 2.1
# ──────────────────────────────────────────────

class TestBugConditionFreeLocalStorageThresholdExists:
    """_resolve_free_local_storage_threshold() 함수가 존재하고 호출 가능해야 한다.

    BUG: 현재 코드에는 이 함수가 없어 ImportError가 발생한다.
    """

    def test_function_is_callable(self):
        """
        **Validates: Requirements 1.1, 1.4, 2.1**

        _resolve_free_local_storage_threshold must exist and be callable.
        This FAILS on unfixed code (ImportError at module level).
        """
        assert callable(_resolve_free_local_storage_threshold), (
            "_resolve_free_local_storage_threshold is not callable"
        )


# ──────────────────────────────────────────────
# Property 1b: _total_local_storage_bytes 기반 퍼센트 임계치 계산
# Validates: Requirements 1.2, 2.2, 2.3, 2.5
# ──────────────────────────────────────────────

class TestBugConditionPercentBasedThreshold:
    """_total_local_storage_bytes가 설정된 태그에서
    _resolve_free_local_storage_threshold()가 퍼센트 기반 임계치를 반환해야 한다.

    BUG: 현재 코드에는 이 함수가 없어 ImportError가 발생한다.
    """

    @given(storage_gb=local_storage_gb)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_threshold_is_percent_based(self, storage_gb):
        """
        **Validates: Requirements 1.2, 2.2, 2.3, 2.5**

        Given _total_local_storage_bytes tag, returns percent-based threshold
        (default 20%), not the 10GB fallback.
        """
        total_bytes = storage_gb * _BYTES_PER_GB
        tags = {"_total_local_storage_bytes": str(total_bytes)}

        display_gb, cw_bytes = _resolve_free_local_storage_threshold(tags)

        expected_cw_bytes = 0.2 * total_bytes
        assert cw_bytes == expected_cw_bytes, (
            f"storage={storage_gb}GB: expected cw_bytes={expected_cw_bytes}, "
            f"got {cw_bytes}. Should be 20% of total, not 10GB fallback."
        )


# ──────────────────────────────────────────────
# Property 1c: 다양한 스토리지 용량에서 임계치가 다름 (10GB 고정 아님)
# Validates: Requirements 1.2, 1.3, 2.3
# ──────────────────────────────────────────────

class TestBugConditionVariableThresholds:
    """다양한 로컬 스토리지 용량(20GB~500GB)에서 임계치가 10GB 고정값이 아닌
    퍼센트 기반이어야 한다."""

    @given(
        storage_a=st.integers(min_value=20, max_value=100),
        storage_b=st.integers(min_value=200, max_value=500),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_different_storage_sizes_produce_different_thresholds(self, storage_a, storage_b):
        """
        **Validates: Requirements 1.2, 1.3, 2.3**

        Different storage sizes must produce different thresholds,
        not a fixed 10GB for all.
        """
        tags_a = {"_total_local_storage_bytes": str(storage_a * _BYTES_PER_GB)}
        tags_b = {"_total_local_storage_bytes": str(storage_b * _BYTES_PER_GB)}

        _, cw_bytes_a = _resolve_free_local_storage_threshold(tags_a)
        _, cw_bytes_b = _resolve_free_local_storage_threshold(tags_b)

        assert cw_bytes_a != cw_bytes_b, (
            f"storage_a={storage_a}GB and storage_b={storage_b}GB produced "
            f"same threshold {cw_bytes_a}. Should be percent-based (different)."
        )
