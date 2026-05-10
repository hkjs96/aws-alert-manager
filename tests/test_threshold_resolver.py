"""
threshold_resolver 단위 테스트 — 임계치 해석 3단계 우선순위 검증
"""

import os
from unittest.mock import patch

import pytest


GB = 1073741824


# ──────────────────────────────────────────────
# _resolve_free_memory_threshold
# ──────────────────────────────────────────────

class TestResolveFreeMemoryThreshold:
    """FreeMemoryGB 임계치 해석 — 3단계 우선순위"""

    def test_명시적_FreeMemoryPct_태그_우선_적용(self):
        from common.threshold_resolver import _resolve_free_memory_threshold

        # 32GB 인스턴스, 30% 임계치 설정
        total_bytes = 32 * GB
        resource_tags = {
            "Threshold_FreeMemoryPct": "30",
            "_total_memory_bytes": str(total_bytes),
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        expected_bytes = 0.30 * total_bytes
        assert abs(cw_bytes - expected_bytes) < 1.0  # float 정밀도
        assert display_gb == round(expected_bytes / GB, 2)

    def test_total_memory_bytes_있으면_기본_20pct_자동_적용(self):
        from common.threshold_resolver import _resolve_free_memory_threshold

        total_bytes = 16 * GB  # 16GB 인스턴스
        resource_tags = {"_total_memory_bytes": str(total_bytes)}

        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        expected_bytes = 0.20 * total_bytes
        assert abs(cw_bytes - expected_bytes) < 1.0
        assert display_gb == round(expected_bytes / GB, 2)

    def test_total_memory_없으면_GB_절대값_폴백(self):
        from common.threshold_resolver import _resolve_free_memory_threshold

        # Threshold_FreeMemoryGB=4 태그
        resource_tags = {"Threshold_FreeMemoryGB": "4"}
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        assert display_gb == 4.0
        assert cw_bytes == 4.0 * GB

    def test_태그_없으면_HARDCODED_DEFAULTS_FreeMemoryGB_사용(self):
        from common.threshold_resolver import _resolve_free_memory_threshold
        from common import HARDCODED_DEFAULTS

        display_gb, cw_bytes = _resolve_free_memory_threshold({})

        expected_gb = HARDCODED_DEFAULTS["FreeMemoryGB"]
        assert display_gb == expected_gb
        assert cw_bytes == expected_gb * GB

    def test_Serverless_v2는_GB_절대값만_사용(self):
        from common.threshold_resolver import _resolve_free_memory_threshold

        # Serverless v2: _total_memory_bytes 있어도 GB 폴백
        resource_tags = {
            "_is_serverless_v2": "true",
            "_total_memory_bytes": str(32 * GB),
            "Threshold_FreeMemoryGB": "3",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        assert display_gb == 3.0
        assert cw_bytes == 3.0 * GB

    def test_FreeMemoryPct_비정상값_fallback(self):
        from common.threshold_resolver import _resolve_free_memory_threshold
        from common import HARDCODED_DEFAULTS

        resource_tags = {"Threshold_FreeMemoryPct": "not-a-number"}
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        expected_gb = HARDCODED_DEFAULTS["FreeMemoryGB"]
        assert display_gb == expected_gb

    def test_FreeMemoryPct_범위_벗어나면_fallback(self):
        from common.threshold_resolver import _resolve_free_memory_threshold
        from common import HARDCODED_DEFAULTS

        resource_tags = {
            "Threshold_FreeMemoryPct": "150",
            "_total_memory_bytes": str(16 * GB),
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        # 범위 초과 → 2단계: _total_memory_bytes 자동 20%
        expected_bytes = 0.20 * 16 * GB
        assert abs(cw_bytes - expected_bytes) < 1.0

    def test_FreeMemoryPct_있지만_total_memory_없으면_GB_fallback(self):
        from common.threshold_resolver import _resolve_free_memory_threshold

        resource_tags = {
            "Threshold_FreeMemoryPct": "20",
            "Threshold_FreeMemoryGB": "5",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(resource_tags)

        assert display_gb == 5.0
        assert cw_bytes == 5.0 * GB


# ──────────────────────────────────────────────
# _resolve_free_local_storage_threshold
# ──────────────────────────────────────────────

class TestResolveFreeLocalStorageThreshold:
    """FreeLocalStorageGB 임계치 해석 — 3단계 우선순위"""

    def test_명시적_FreeLocalStoragePct_태그_우선(self):
        from common.threshold_resolver import _resolve_free_local_storage_threshold

        total_bytes = 200 * GB
        resource_tags = {
            "Threshold_FreeLocalStoragePct": "15",
            "_total_local_storage_bytes": str(total_bytes),
        }
        display_gb, cw_bytes = _resolve_free_local_storage_threshold(resource_tags)

        expected_bytes = 0.15 * total_bytes
        assert abs(cw_bytes - expected_bytes) < 1.0
        assert display_gb == round(expected_bytes / GB, 2)

    def test_total_local_storage_있으면_기본_20pct_자동_적용(self):
        from common.threshold_resolver import _resolve_free_local_storage_threshold

        total_bytes = 100 * GB
        resource_tags = {"_total_local_storage_bytes": str(total_bytes)}

        display_gb, cw_bytes = _resolve_free_local_storage_threshold(resource_tags)

        expected_bytes = 0.20 * total_bytes
        assert abs(cw_bytes - expected_bytes) < 1.0

    def test_total_local_storage_없으면_GB_절대값_폴백(self):
        from common.threshold_resolver import _resolve_free_local_storage_threshold

        resource_tags = {"Threshold_FreeLocalStorageGB": "10"}
        display_gb, cw_bytes = _resolve_free_local_storage_threshold(resource_tags)

        assert display_gb == 10.0
        assert cw_bytes == 10.0 * GB

    def test_태그_없으면_HARDCODED_DEFAULTS_사용(self):
        from common.threshold_resolver import _resolve_free_local_storage_threshold
        from common import HARDCODED_DEFAULTS

        display_gb, cw_bytes = _resolve_free_local_storage_threshold({})

        expected_gb = HARDCODED_DEFAULTS["FreeLocalStorageGB"]
        assert display_gb == expected_gb
        assert cw_bytes == expected_gb * GB


# ──────────────────────────────────────────────
# resolve_threshold
# ──────────────────────────────────────────────

class TestResolveThreshold:
    """통합 임계치 해석 진입점"""

    def test_FreeMemoryGB_metric_은_resolve_free_memory_호출(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "FreeableMemory"}
        resource_tags = {"Threshold_FreeMemoryGB": "3"}  # 레거시 태그 이름 호환
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == 3.0
        assert cw_thr == 3.0 * GB

    def test_FreeLocalStorageGB_metric_은_resolve_free_local_storage_호출(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "FreeLocalStorage"}
        resource_tags = {"Threshold_FreeLocalStorageGB": "5"}  # 레거시 태그 이름 호환
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == 5.0
        assert cw_thr == 5.0 * GB

    def test_일반_metric_태그_우선_적용(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "CPU"}
        resource_tags = {"Threshold_CPU": "90"}
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == 90.0
        assert cw_thr == 90.0

    def test_일반_metric_HARDCODED_DEFAULTS_폴백(self):
        from common.threshold_resolver import resolve_threshold
        from common import HARDCODED_DEFAULTS

        alarm_def = {"metric": "CPU"}
        display_thr, cw_thr = resolve_threshold(alarm_def, {})

        expected = HARDCODED_DEFAULTS["CPU"]
        assert display_thr == expected
        assert cw_thr == expected

    def test_transform_threshold_적용(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {
            "metric": "FreeStorageGB",
            "transform_threshold": lambda x: x * GB,
        }
        resource_tags = {"Threshold_FreeStorageGB": "10"}
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == 10.0
        assert cw_thr == 10.0 * GB

    def test_transform_없으면_display와_cw_동일(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "Connections"}
        resource_tags = {"Threshold_Connections": "200"}
        display_thr, cw_thr = resolve_threshold(alarm_def, resource_tags)

        assert display_thr == cw_thr == 200.0

    def test_환경_변수_DEFAULT_threshold_중간_우선순위(self):
        from common.threshold_resolver import resolve_threshold

        alarm_def = {"metric": "CPU"}
        with patch.dict(os.environ, {"DEFAULT_CPU_THRESHOLD": "70"}):
            display_thr, cw_thr = resolve_threshold(alarm_def, {})

        assert display_thr == 70.0
