"""
PBT: DocDB 알람 정의가 표준 메트릭 기준과 일치하는지 검증.

표준 메트릭 (docs/Managed Service 모니터링 표준메트릭.xlsx 기준):
- CPUUtilization, FreeableMemory, DatabaseConnectionsMax → 내부 키: CPU, FreeMemoryGB, Connections

Property 1: DocDB 하드코딩 알람은 정확히 표준 3개 메트릭만 포함
Property 2: 제거된 메트릭(FreeLocalStorageGB, ReadLatency, WriteLatency)은 하드코딩에 없음
Property 3: DocDB 알람 정의의 네임스페이스/디멘션 정합성
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_registry import (
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
    _HARDCODED_METRIC_KEYS,
    _NAMESPACE_MAP,
    _DIMENSION_KEY_MAP,
)


# ──────────────────────────────────────────────
# 표준 메트릭 정의 (ground truth)
# ──────────────────────────────────────────────

DOCDB_STANDARD_METRICS = {"CPU", "FreeMemoryGB", "Connections"}
DOCDB_REMOVED_METRICS = {"FreeLocalStorageGB", "ReadLatency", "WriteLatency"}


# ──────────────────────────────────────────────
# Property 1: DocDB 하드코딩 알람 == 표준 3개 메트릭
# ──────────────────────────────────────────────

def test_property_1_docdb_hardcoded_equals_standard():
    """DocDB 하드코딩 알람 메트릭 키 집합이 표준 메트릭과 정확히 일치."""
    defs = _get_alarm_defs("DocDB")
    actual_metrics = {d["metric"] for d in defs}
    assert actual_metrics == DOCDB_STANDARD_METRICS, (
        f"Expected {DOCDB_STANDARD_METRICS}, got {actual_metrics}"
    )


def test_property_1_hardcoded_metric_keys_match():
    """_HARDCODED_METRIC_KEYS['DocDB']가 표준 메트릭과 일치."""
    assert _HARDCODED_METRIC_KEYS["DocDB"] == DOCDB_STANDARD_METRICS


def test_property_1_dynamic_hardcoded_keys_match():
    """_get_hardcoded_metric_keys('DocDB')가 표준 메트릭과 일치."""
    assert _get_hardcoded_metric_keys("DocDB") == DOCDB_STANDARD_METRICS


# ──────────────────────────────────────────────
# Property 2: 제거된 메트릭이 하드코딩에 없음
# ──────────────────────────────────────────────

@settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
@given(removed_metric=st.sampled_from(sorted(DOCDB_REMOVED_METRICS)))
def test_property_2_removed_metrics_not_in_hardcoded(removed_metric):
    """제거된 메트릭(FreeLocalStorageGB, ReadLatency, WriteLatency)이 DocDB 하드코딩에 없음."""
    defs = _get_alarm_defs("DocDB")
    actual_metrics = {d["metric"] for d in defs}
    assert removed_metric not in actual_metrics, (
        f"{removed_metric} should not be in DocDB hardcoded alarms"
    )
    assert removed_metric not in _HARDCODED_METRIC_KEYS["DocDB"], (
        f"{removed_metric} should not be in _HARDCODED_METRIC_KEYS['DocDB']"
    )


# ──────────────────────────────────────────────
# Property 3: DocDB 알람 정의 네임스페이스/디멘션 정합성
# ──────────────────────────────────────────────

def test_property_3_docdb_namespace_consistency():
    """모든 DocDB 알람 정의의 namespace == 'AWS/DocDB'."""
    defs = _get_alarm_defs("DocDB")
    for d in defs:
        assert d["namespace"] == "AWS/DocDB", (
            f"{d['metric']} has namespace {d['namespace']}, expected AWS/DocDB"
        )


def test_property_3_docdb_dimension_key_consistency():
    """모든 DocDB 알람 정의의 dimension_key == 'DBInstanceIdentifier'."""
    defs = _get_alarm_defs("DocDB")
    for d in defs:
        assert d["dimension_key"] == "DBInstanceIdentifier", (
            f"{d['metric']} has dimension_key {d['dimension_key']}"
        )


def test_property_3_namespace_map_consistency():
    """_NAMESPACE_MAP['DocDB'] == ['AWS/DocDB']."""
    assert _NAMESPACE_MAP["DocDB"] == ["AWS/DocDB"]


def test_property_3_dimension_key_map_consistency():
    """_DIMENSION_KEY_MAP['DocDB'] == 'DBInstanceIdentifier'."""
    assert _DIMENSION_KEY_MAP["DocDB"] == "DBInstanceIdentifier"
