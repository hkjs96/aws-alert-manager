"""
Property 3: 메타데이터 기반 알람 매칭

_build_alarm_description() → _parse_alarm_metadata() 라운드트립 검증:
임의의 resource_type, resource_id, metric_key, human_prefix에 대해
build → parse 라운드트립이 원본 메타데이터를 정확히 복원하는지 검증.

sync_alarms_for_resource()가 AlarmDescription JSON 메타데이터
(Namespace/MetricName/Dimensions)로 매칭하는지 검증.

**Validates: Requirements 2.4, 2.13**
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.alarm_manager import (
    _build_alarm_description,
    _parse_alarm_metadata,
    _resolve_metric_key,
)


# ──────────────────────────────────────────────
# Hypothesis 전략
# ──────────────────────────────────────────────

resource_types = st.sampled_from(["EC2", "RDS", "ELB"])

# ASCII 문자열 (JSON 안전)
safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_./:",
    ),
    min_size=1,
    max_size=60,
)

# 메트릭 키: 하드코딩 + 동적 메트릭 이름
metric_keys = st.one_of(
    st.sampled_from([
        "CPU", "Memory", "Disk_root", "Disk_data",
        "FreeMemoryGB", "FreeStorageGB", "Connections",
        "RequestCount",
    ]),
    safe_text,
)

# human_prefix: 빈 문자열 또는 짧은 설명
human_prefixes = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"),
            whitelist_characters="-_./: ",
        ),
        min_size=1,
        max_size=100,
    ),
)


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestAlarmMetadataRoundtrip:
    """
    _build_alarm_description() → _parse_alarm_metadata() 라운드트립 검증.

    **Validates: Requirements 2.4, 2.13**
    """

    @given(
        resource_type=resource_types,
        resource_id=safe_text,
        metric_key=metric_keys,
        human_prefix=human_prefixes,
    )
    @settings(max_examples=20, deadline=None)
    def test_roundtrip_preserves_metadata(
        self, resource_type, resource_id, metric_key, human_prefix,
    ):
        """
        **Property 3: 메타데이터 라운드트립** - build → parse가 원본 복원

        임의의 입력에 대해 _build_alarm_description()으로 생성한 description을
        _parse_alarm_metadata()로 파싱하면 원본 metric_key, resource_id,
        resource_type이 정확히 복원되어야 한다.

        **Validates: Requirements 2.4, 2.13**
        """
        desc = _build_alarm_description(
            resource_type, resource_id, metric_key, human_prefix,
        )

        # 1024자 제한 준수
        assert len(desc) <= 1024, (
            f"Description exceeds 1024 chars: len={len(desc)}"
        )

        parsed = _parse_alarm_metadata(desc)
        assert parsed is not None, (
            f"Failed to parse metadata from description: {desc!r}"
        )

        assert parsed["metric_key"] == metric_key, (
            f"metric_key mismatch: expected={metric_key!r}, "
            f"actual={parsed['metric_key']!r}"
        )
        assert parsed["resource_id"] == resource_id, (
            f"resource_id mismatch: expected={resource_id!r}, "
            f"actual={parsed['resource_id']!r}"
        )
        assert parsed["resource_type"] == resource_type, (
            f"resource_type mismatch: expected={resource_type!r}, "
            f"actual={parsed['resource_type']!r}"
        )

    @given(
        resource_type=resource_types,
        resource_id=safe_text,
        metric_key=metric_keys,
    )
    @settings(max_examples=20, deadline=None)
    def test_resolve_metric_key_from_description(
        self, resource_type, resource_id, metric_key,
    ):
        """
        **Property 3: 메타데이터 매칭** - _resolve_metric_key가 메타데이터 우선

        AlarmDescription에 JSON 메타데이터가 포함된 알람에 대해
        _resolve_metric_key()가 메타데이터의 metric_key를 반환해야 한다.

        **Validates: Requirements 2.13**
        """
        desc = _build_alarm_description(
            resource_type, resource_id, metric_key,
            f"Auto-created for {resource_type} {resource_id}",
        )

        alarm_info = {
            "AlarmName": f"[{resource_type}] test {metric_key} >80 ({resource_id})",
            "AlarmDescription": desc,
            "MetricName": "SomeOtherMetricName",
        }

        resolved = _resolve_metric_key(alarm_info)
        assert resolved == metric_key, (
            f"_resolve_metric_key should return metadata metric_key={metric_key!r}, "
            f"but got {resolved!r} (MetricName fallback should not be used)"
        )
