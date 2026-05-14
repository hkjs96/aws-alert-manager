"""
Preservation Property Test - 정적 매핑 및 기존 임계치 로직 보존

Property 2 (Preservation): _INSTANCE_CLASS_MEMORY_MAP에 이미 존재하는 인스턴스 클래스,
Serverless v2, 태그 기반 임계치 오버라이드 등 기존 동작이 수정 후에도 동일하게
유지되는지 검증한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

EXPECTED: These tests PASS on unfixed code (existing behavior is correct).
"""

from unittest.mock import patch

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from common.alarm_manager import _resolve_free_memory_threshold
from common.collectors.rds import (
    _enrich_aurora_metadata,
    _enrich_rds_memory,
    _INSTANCE_CLASS_MEMORY_MAP,
)
from common import HARDCODED_DEFAULTS

_BYTES_PER_GB = 1073741824  # 1024**3

# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

# Instance classes that ARE in the static mapping
mapped_instance_class = st.sampled_from(list(_INSTANCE_CLASS_MEMORY_MAP.keys()))

# Valid percent values for Threshold_FreeMemoryPct (0 < pct < 100)
valid_pct = st.floats(min_value=1.0, max_value=99.0, allow_nan=False, allow_infinity=False)

# Valid GB values for Threshold_FreeMemoryGB
valid_gb = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)


def _make_db_instance(instance_class: str, db_id: str = "test-db-1") -> dict:
    """테스트용 DB 인스턴스 dict 생성."""
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceClass": instance_class,
        "Engine": "mysql",
        "DBInstanceArn": f"arn:aws:rds:us-east-1:123:db:{db_id}",
    }


def _make_aurora_db_instance(instance_class: str, db_id: str = "aurora-test-1",
                             cluster_id: str = "aurora-cluster-1") -> dict:
    """테스트용 Aurora DB 인스턴스 dict 생성."""
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceClass": instance_class,
        "Engine": "aurora-mysql",
        "DBClusterIdentifier": cluster_id,
        "DBInstanceArn": f"arn:aws:rds:us-east-1:123:db:{db_id}",
    }


def _mock_cluster_cache(db_id: str = "aurora-test-1",
                        is_writer: bool = True) -> dict:
    """Aurora 클러스터 캐시 mock 생성 (Provisioned, non-serverless)."""
    return {
        "aurora-cluster-1": {
            "DBClusterIdentifier": "aurora-cluster-1",
            "DBClusterMembers": [
                {
                    "DBInstanceIdentifier": db_id,
                    "IsClusterWriter": is_writer,
                },
            ],
        },
    }


# ──────────────────────────────────────────────
# Property 2a: 정적 매핑 인스턴스 → _enrich_rds_memory() 보존
# Validates: Requirements 3.5, 3.6
# ──────────────────────────────────────────────

class TestPreservationRDSMemoryEnrichment:
    """_INSTANCE_CLASS_MEMORY_MAP에 있는 인스턴스 클래스에 대해
    _enrich_rds_memory()가 정적 매핑 값으로 _total_memory_bytes를 설정하는지 검증."""

    @given(instance_class=mapped_instance_class)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_enrich_rds_memory_uses_static_mapping(self, instance_class):
        """
        **Validates: Requirements 3.5, 3.6**

        For any instance class IN _INSTANCE_CLASS_MEMORY_MAP,
        _enrich_rds_memory() sets _total_memory_bytes to the static mapping value.
        """
        db_instance = _make_db_instance(instance_class)
        tags: dict = {}

        _enrich_rds_memory(db_instance, tags)

        expected_bytes = _INSTANCE_CLASS_MEMORY_MAP[instance_class]
        assert "_total_memory_bytes" in tags, (
            f"_enrich_rds_memory did not set _total_memory_bytes for "
            f"mapped class '{instance_class}'"
        )
        assert tags["_total_memory_bytes"] == str(expected_bytes), (
            f"Expected _total_memory_bytes={expected_bytes} for "
            f"'{instance_class}', got {tags['_total_memory_bytes']}"
        )
        assert tags["_db_instance_class"] == instance_class


# ──────────────────────────────────────────────
# Property 2b: 정적 매핑 인스턴스 → _enrich_aurora_metadata() 보존
# Validates: Requirements 3.5, 3.6
# ──────────────────────────────────────────────

class TestPreservationAuroraMemoryEnrichment:
    """_INSTANCE_CLASS_MEMORY_MAP에 있는 Provisioned Aurora 인스턴스에 대해
    _enrich_aurora_metadata()가 정적 매핑 값으로 _total_memory_bytes를 설정하는지 검증."""

    @given(instance_class=mapped_instance_class)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_enrich_aurora_metadata_uses_static_mapping(self, instance_class):
        """
        **Validates: Requirements 3.5, 3.6**

        For any Provisioned Aurora instance class IN _INSTANCE_CLASS_MEMORY_MAP,
        _enrich_aurora_metadata() sets _total_memory_bytes to the static mapping value.
        """
        db_id = "aurora-test-1"
        db_instance = _make_aurora_db_instance(instance_class, db_id=db_id)
        tags: dict = {}
        cluster_cache = _mock_cluster_cache(db_id=db_id)

        _enrich_aurora_metadata(db_instance, tags, cluster_cache)

        expected_bytes = _INSTANCE_CLASS_MEMORY_MAP[instance_class]
        assert tags.get("_is_serverless_v2") == "false", (
            f"Non-serverless instance class '{instance_class}' should have "
            f"_is_serverless_v2='false'"
        )
        assert "_total_memory_bytes" in tags, (
            f"_enrich_aurora_metadata did not set _total_memory_bytes for "
            f"mapped class '{instance_class}'"
        )
        assert tags["_total_memory_bytes"] == str(expected_bytes), (
            f"Expected _total_memory_bytes={expected_bytes} for "
            f"'{instance_class}', got {tags['_total_memory_bytes']}"
        )


# ──────────────────────────────────────────────
# Property 2c: Serverless v2 → GB 절대값만 사용 (퍼센트 기반 스킵)
# Validates: Requirements 3.3
# ──────────────────────────────────────────────

class TestPreservationServerlessV2GBOnly:
    """Serverless v2 인스턴스에서 _resolve_free_memory_threshold()가
    퍼센트 기반 임계치를 적용하지 않고 GB 절대값만 사용하는지 검증."""

    @given(
        total_mem_gb=st.floats(min_value=1.0, max_value=256.0,
                               allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_serverless_v2_uses_gb_absolute_only(self, total_mem_gb):
        """
        **Validates: Requirements 3.3**

        Serverless v2 instances (_is_serverless_v2=true) use GB absolute value
        only, skipping percent-based threshold regardless of _total_memory_bytes.
        """
        total_mem_bytes = int(total_mem_gb * _BYTES_PER_GB)
        tags = {
            "_is_serverless_v2": "true",
            "_total_memory_bytes": str(total_mem_bytes),
        }

        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        # Serverless v2 uses HARDCODED_DEFAULTS["FreeMemoryGB"] = 2.0
        expected_gb = HARDCODED_DEFAULTS["FreeMemoryGB"]
        assert display_gb == expected_gb, (
            f"Serverless v2 should use GB fallback ({expected_gb}), "
            f"got display_gb={display_gb}"
        )
        assert cw_bytes == expected_gb * _BYTES_PER_GB, (
            f"Serverless v2 cw_bytes should be {expected_gb * _BYTES_PER_GB}, "
            f"got {cw_bytes}"
        )


# ──────────────────────────────────────────────
# Property 2d: Threshold_FreeMemoryPct 태그 → 퍼센트 임계치 우선 적용
# Validates: Requirements 3.2
# ──────────────────────────────────────────────

class TestPreservationFreeMemoryPctTag:
    """Threshold_FreeMemoryPct 태그가 명시적으로 설정된 경우
    태그 값을 퍼센트 기반 임계치로 최우선 사용하는지 검증."""

    @given(
        pct=valid_pct,
        instance_class=mapped_instance_class,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_freememorypct_tag_takes_priority(self, pct, instance_class):
        """
        **Validates: Requirements 3.2**

        When Threshold_FreeMemoryPct tag is present with valid value,
        _resolve_free_memory_threshold() uses the tag percent value as priority.
        """
        total_mem_bytes = _INSTANCE_CLASS_MEMORY_MAP[instance_class]
        tags = {
            "Threshold_FreeMemoryPct": str(pct),
            "_total_memory_bytes": str(total_mem_bytes),
        }

        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        expected_cw_bytes = (pct / 100) * total_mem_bytes
        expected_display_gb = round(expected_cw_bytes / _BYTES_PER_GB, 2)

        assert cw_bytes == expected_cw_bytes, (
            f"FreeMemoryPct={pct}% with total_mem={total_mem_bytes}: "
            f"expected cw_bytes={expected_cw_bytes}, got {cw_bytes}"
        )
        assert display_gb == expected_display_gb, (
            f"FreeMemoryPct={pct}% with total_mem={total_mem_bytes}: "
            f"expected display_gb={expected_display_gb}, got {display_gb}"
        )


# ──────────────────────────────────────────────
# Property 2e: Threshold_FreeMemoryGB 태그 + _total_memory_bytes 미존재 → GB 절대값
# Validates: Requirements 3.1
# ──────────────────────────────────────────────

class TestPreservationFreeMemoryGBTagFallback:
    """Threshold_FreeMemoryGB 태그가 있고 _total_memory_bytes가 없는 경우
    GB 절대값을 사용하는지 검증."""

    @given(gb=valid_gb)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_freememorygb_tag_used_without_total_memory(self, gb):
        """
        **Validates: Requirements 3.1**

        When Threshold_FreeMemoryGB tag is present and _total_memory_bytes
        is absent, _resolve_free_memory_threshold() uses the GB absolute value.
        """
        tags = {
            "Threshold_FreeMemoryGB": str(gb),
        }

        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        assert display_gb == gb, (
            f"Expected display_gb={gb}, got {display_gb}"
        )
        assert cw_bytes == gb * _BYTES_PER_GB, (
            f"Expected cw_bytes={gb * _BYTES_PER_GB}, got {cw_bytes}"
        )
