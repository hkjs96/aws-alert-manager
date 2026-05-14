"""
Bug Condition Exploration Test - 매핑 누락 인스턴스 클래스의 _total_memory_bytes 미설정

Property 1 (Bug Condition): _INSTANCE_CLASS_MEMORY_MAP에 없는 인스턴스 클래스를
사용하는 RDS/Aurora 프로비저닝 인스턴스에서 _total_memory_bytes 내부 태그가
설정되지 않아, _resolve_free_memory_threshold()가 3단계 폴백(고정 2GB)으로
진입하는 버그.

Bug Condition: isBugCondition(input) where
  input.is_serverless == false
  AND input.instance_class NOT IN _INSTANCE_CLASS_MEMORY_MAP
  AND input.instance_class starts with "db."
  AND input.instance_class != "db.serverless"

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**

EXPECTED: These tests FAIL on unfixed code because _enrich_rds_memory() and
_enrich_aurora_metadata() only look up _INSTANCE_CLASS_MEMORY_MAP and skip
_total_memory_bytes when the class is not found.
"""

from unittest.mock import patch, MagicMock

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_manager import _resolve_free_memory_threshold
from common.collectors.rds import (
    _enrich_aurora_metadata,
    _enrich_rds_memory,
    _INSTANCE_CLASS_MEMORY_MAP,
    _instance_class_memory_cache,
)

# ──────────────────────────────────────────────
# Strategy: instance classes NOT in _INSTANCE_CLASS_MEMORY_MAP
# These are real AWS instance classes that are missing from the static map
# ──────────────────────────────────────────────

_UNMAPPED_INSTANCE_CLASSES = [
    "db.r5.large",
    "db.r5.xlarge",
    "db.r5.2xlarge",
    "db.r6i.large",
    "db.r6i.xlarge",
    "db.m6i.xlarge",
    "db.m6i.2xlarge",
    "db.t3.nano",
    "db.t2.micro",
    "db.t2.small",
    "db.m5d.large",
    "db.x2g.large",
]

# Verify these are actually NOT in the map (safety check)
_UNMAPPED_INSTANCE_CLASSES = [
    c for c in _UNMAPPED_INSTANCE_CLASSES
    if c not in _INSTANCE_CLASS_MEMORY_MAP
]

unmapped_instance_class = st.sampled_from(_UNMAPPED_INSTANCE_CLASSES)

# 매핑 누락 인스턴스 클래스의 실제 메모리 (MiB, API 응답 단위)
_UNMAPPED_MEMORY_MIB: dict[str, int] = {
    "db.r5.large": 16384,
    "db.r5.xlarge": 32768,
    "db.r5.2xlarge": 65536,
    "db.r6i.large": 16384,
    "db.r6i.xlarge": 32768,
    "db.m6i.xlarge": 16384,
    "db.m6i.2xlarge": 32768,
    "db.t3.nano": 512,
    "db.t2.micro": 1024,
    "db.t2.small": 2048,
    "db.m5d.large": 8192,
    "db.x2g.large": 32768,
}


def _make_mock_rds_client():
    """describe_db_instance_classes API를 모킹하는 RDS 클라이언트 생성."""
    mock_rds = MagicMock()

    def _describe_db_instance_classes(**kwargs):
        ic = kwargs.get("DBInstanceClass", "")
        mem = _UNMAPPED_MEMORY_MIB.get(ic)
        if mem is not None:
            return {"DBInstanceClasses": [{"Memory": mem}]}
        return {"DBInstanceClasses": []}

    mock_rds.describe_db_instance_classes.side_effect = (
        _describe_db_instance_classes
    )
    return mock_rds


def _make_db_instance(instance_class: str, db_id: str = "test-db-1",
                      engine: str = "mysql") -> dict:
    """테스트용 DB 인스턴스 dict 생성."""
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceClass": instance_class,
        "Engine": engine,
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
# Property 1a: _enrich_rds_memory - 매핑 누락 시 _total_memory_bytes 설정 검증
# Validates: Requirements 1.1, 2.1
# ──────────────────────────────────────────────

class TestBugConditionRDSMemoryEnrichment:
    """_enrich_rds_memory()가 매핑에 없는 인스턴스 클래스에서도
    _total_memory_bytes를 설정해야 한다.

    BUG: 현재 코드는 _INSTANCE_CLASS_MEMORY_MAP.get()이 None을 반환하면
    warning 로그만 남기고 _total_memory_bytes를 설정하지 않는다.
    """

    @given(instance_class=unmapped_instance_class)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_enrich_rds_memory_sets_total_memory_bytes(self, instance_class):
        """
        **Validates: Requirements 1.1, 2.1**

        For any instance class NOT in _INSTANCE_CLASS_MEMORY_MAP,
        _enrich_rds_memory() should still set _total_memory_bytes.
        This FAILS on unfixed code (proves the bug exists).
        """
        _instance_class_memory_cache.clear()
        db_instance = _make_db_instance(instance_class)
        tags: dict = {}

        with patch(
            "common.collectors.rds._get_rds_client",
            return_value=_make_mock_rds_client(),
        ):
            _enrich_rds_memory(db_instance, tags)

        assert "_total_memory_bytes" in tags, (
            f"_enrich_rds_memory({{DBInstanceClass: '{instance_class}'}}) "
            f"did not set _total_memory_bytes. tags={tags}"
        )


# ──────────────────────────────────────────────
# Property 1b: _enrich_aurora_metadata - 매핑 누락 시 _total_memory_bytes 설정 검증
# Validates: Requirements 1.1, 2.2
# ──────────────────────────────────────────────

class TestBugConditionAuroraMemoryEnrichment:
    """_enrich_aurora_metadata()가 매핑에 없는 Provisioned 인스턴스 클래스에서도
    _total_memory_bytes를 설정해야 한다.

    BUG: 현재 코드는 Provisioned 분기에서 _INSTANCE_CLASS_MEMORY_MAP.get()이
    None을 반환하면 warning 로그만 남기고 _total_memory_bytes를 설정하지 않는다.
    """

    @given(instance_class=unmapped_instance_class)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_enrich_aurora_metadata_sets_total_memory_bytes(self, instance_class):
        """
        **Validates: Requirements 1.1, 2.2**

        For any Provisioned Aurora instance class NOT in _INSTANCE_CLASS_MEMORY_MAP,
        _enrich_aurora_metadata() should still set _total_memory_bytes.
        This FAILS on unfixed code (proves the bug exists).
        """
        _instance_class_memory_cache.clear()
        db_id = "aurora-test-1"
        db_instance = _make_aurora_db_instance(instance_class, db_id=db_id)
        tags: dict = {}
        cluster_cache = _mock_cluster_cache(db_id=db_id)

        with patch(
            "common.collectors.rds._get_rds_client",
            return_value=_make_mock_rds_client(),
        ), patch(
            "common.collectors.rds._get_cluster_info",
            side_effect=lambda cid: cluster_cache.get(cid),
        ):
            _enrich_aurora_metadata(db_instance, tags, cluster_cache)

        assert "_total_memory_bytes" in tags, (
            f"_enrich_aurora_metadata({{DBInstanceClass: '{instance_class}'}}) "
            f"did not set _total_memory_bytes. tags={tags}"
        )


# ──────────────────────────────────────────────
# Property 1c: _resolve_free_memory_threshold - 퍼센트 기반 임계치 검증
# Validates: Requirements 1.2, 2.3, 2.4
# ──────────────────────────────────────────────

class TestBugConditionFreeMemoryThresholdFallback:
    """매핑 누락 인스턴스에서 _total_memory_bytes가 미설정되면
    _resolve_free_memory_threshold()가 3단계 폴백(2GB)으로 진입한다.

    BUG: _total_memory_bytes가 없으면 2단계(퍼센트 기반 20%)를 건너뛰고
    HARDCODED_DEFAULTS["FreeMemoryGB"] = 2.0 고정값을 사용한다.
    """

    @given(instance_class=unmapped_instance_class)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_threshold_is_percent_based_not_2gb_fallback(self, instance_class):
        """
        **Validates: Requirements 1.2, 2.3, 2.4**

        For any unmapped instance class, after enrichment the threshold
        should be percent-based (not the 2GB hardcoded fallback).
        This FAILS on unfixed code because _total_memory_bytes is never set,
        so _resolve_free_memory_threshold returns (2.0, 2147483648.0).
        """
        _instance_class_memory_cache.clear()
        db_instance = _make_db_instance(instance_class)
        tags: dict = {}

        with patch(
            "common.collectors.rds._get_rds_client",
            return_value=_make_mock_rds_client(),
        ):
            _enrich_rds_memory(db_instance, tags)

        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)

        # 2GB fallback = (2.0, 2147483648.0) — this is the buggy behavior
        fallback_cw_bytes = 2.0 * 1073741824  # 2147483648.0

        assert cw_bytes != fallback_cw_bytes, (
            f"_resolve_free_memory_threshold returned 2GB fallback "
            f"(display={display_gb}, cw_bytes={cw_bytes}) for instance class "
            f"'{instance_class}'. Expected percent-based threshold from "
            f"_total_memory_bytes, not hardcoded 2GB."
        )
