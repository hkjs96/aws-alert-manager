"""
Threshold Resolver — 통합 임계치 해석

FreeMemoryGB/FreeLocalStorageGB 퍼센트 기반 임계치 해석 중복을 제거하고,
모든 임계치 해석을 단일 진입점으로 통합한다.
"""

import logging

from common.tag_resolver import get_threshold

logger = logging.getLogger(__name__)


def _resolve_free_memory_threshold(
    resource_tags: dict,
) -> tuple[float, float]:
    """FreeMemoryGB 임계치를 퍼센트 또는 GB 기반으로 해석.

    우선순위:
    1. Threshold_FreeMemoryPct 태그 (명시적 퍼센트, 프로비저닝 인스턴스만)
    2. _total_memory_bytes 존재 + 비서버리스 시 HARDCODED_DEFAULTS["FreeMemoryPct"] 자동 적용
    3. Threshold_FreeMemoryGB 태그 또는 HARDCODED_DEFAULTS["FreeMemoryGB"] (절대값 폴백)

    Serverless v2는 ACU에 따라 메모리가 동적 변동하므로 퍼센트 기반 임계치를 적용하지 않는다.
    Serverless v2에서는 ACUUtilization 알람이 메모리 압박을 대신 감지한다.

    Returns:
        (display_threshold_gb, cw_threshold_bytes) 튜플.
    """
    is_serverless = resource_tags.get("_is_serverless_v2") == "true"
    total_mem_raw = resource_tags.get("_total_memory_bytes")

    # Serverless v2: 퍼센트 기반 스킵 → GB 절대값만 사용
    if is_serverless:
        gb = get_threshold(resource_tags, "FreeMemoryGB")
        return (gb, gb * 1073741824)

    # 1단계: 명시적 Threshold_FreeMemoryPct 태그
    pct_raw = resource_tags.get("Threshold_FreeMemoryPct")
    if pct_raw is not None:
        try:
            pct = float(pct_raw)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid Threshold_FreeMemoryPct=%r (non-numeric): falling back",
                pct_raw,
            )
        else:
            if not (0 < pct < 100):
                logger.warning(
                    "Invalid Threshold_FreeMemoryPct=%s (must be 0 < pct < 100): falling back",
                    pct_raw,
                )
            elif total_mem_raw is None:
                logger.warning(
                    "Threshold_FreeMemoryPct=%s but _total_memory_bytes missing: falling back to GB",
                    pct_raw,
                )
            else:
                total_mem = float(total_mem_raw)
                cw_bytes = (pct / 100) * total_mem
                display_gb = round(cw_bytes / 1073741824, 2)
                return (display_gb, cw_bytes)

    # 2단계: _total_memory_bytes 있으면 기본 퍼센트(20%) 자동 적용
    if total_mem_raw is not None:
        from common import HARDCODED_DEFAULTS
        default_pct = HARDCODED_DEFAULTS.get("FreeMemoryPct", 20.0)
        total_mem = float(total_mem_raw)
        cw_bytes = (default_pct / 100) * total_mem
        display_gb = round(cw_bytes / 1073741824, 2)
        return (display_gb, cw_bytes)

    # 3단계: GB 절대값 폴백
    gb = get_threshold(resource_tags, "FreeMemoryGB")
    return (gb, gb * 1073741824)


def _resolve_free_local_storage_threshold(
    resource_tags: dict,
) -> tuple[float, float]:
    """FreeLocalStorageGB 임계치를 퍼센트 또는 GB 기반으로 해석.

    우선순위:
    1. Threshold_FreeLocalStoragePct 태그 (명시적 퍼센트) + _total_local_storage_bytes 필요
    2. _total_local_storage_bytes 존재 시 HARDCODED_DEFAULTS["FreeLocalStoragePct"] 자동 적용
    3. Threshold_FreeLocalStorageGB 태그 또는 HARDCODED_DEFAULTS["FreeLocalStorageGB"] (절대값 폴백)

    Returns:
        (display_threshold_gb, cw_threshold_bytes) 튜플.
    """
    total_storage_raw = resource_tags.get("_total_local_storage_bytes")

    # 1단계: 명시적 Threshold_FreeLocalStoragePct 태그
    pct_raw = resource_tags.get("Threshold_FreeLocalStoragePct")
    if pct_raw is not None:
        try:
            pct = float(pct_raw)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid Threshold_FreeLocalStoragePct=%r (non-numeric): falling back",
                pct_raw,
            )
        else:
            if not (0 < pct < 100):
                logger.warning(
                    "Invalid Threshold_FreeLocalStoragePct=%s (must be 0 < pct < 100): falling back",
                    pct_raw,
                )
            elif total_storage_raw is None:
                logger.warning(
                    "Threshold_FreeLocalStoragePct=%s but _total_local_storage_bytes missing: "
                    "falling back to GB",
                    pct_raw,
                )
            else:
                total_storage = float(total_storage_raw)
                cw_bytes = (pct / 100) * total_storage
                display_gb = round(cw_bytes / 1073741824, 2)
                return (display_gb, cw_bytes)

    # 2단계: _total_local_storage_bytes 있으면 기본 퍼센트(20%) 자동 적용
    if total_storage_raw is not None:
        from common import HARDCODED_DEFAULTS
        default_pct = HARDCODED_DEFAULTS.get("FreeLocalStoragePct", 20.0)
        total_storage = float(total_storage_raw)
        cw_bytes = (default_pct / 100) * total_storage
        display_gb = round(cw_bytes / 1073741824, 2)
        return (display_gb, cw_bytes)

    # 3단계: GB 절대값 폴백
    gb = get_threshold(resource_tags, "FreeLocalStorageGB")
    return (gb, gb * 1073741824)


def resolve_threshold(
    alarm_def: dict,
    resource_tags: dict,
) -> tuple[float, float]:
    """통합 임계치 해석 — 4곳 중복 분기를 단일 함수로 통합.

    Returns:
        (display_threshold, cw_threshold) 튜플.
    """
    metric = alarm_def["metric"]

    if metric == "FreeMemoryGB":
        return _resolve_free_memory_threshold(resource_tags)

    if metric == "FreeLocalStorageGB":
        return _resolve_free_local_storage_threshold(resource_tags)

    display_thr = get_threshold(resource_tags, metric)
    transform = alarm_def.get("transform_threshold")
    cw_thr = transform(display_thr) if transform else display_thr
    return (display_thr, cw_thr)
