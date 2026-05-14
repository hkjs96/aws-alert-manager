"""
Preservation Property Tests — 알람 이름 포맷 변경 시 보존되어야 하는 동작 검증

Property 2 (Preservation): 255자 Truncate, Short_ID 추출, resource_type 파싱,
AlarmDescription 메타데이터 등 기존 동작이 수정 후에도 동일하게 유지되는지 검증한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

EXPECTED: These tests PASS on UNFIXED code (confirms baseline behavior to preserve).
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_naming import (
    _pretty_alarm_name,
    _shorten_elb_resource_id,
    _build_alarm_description,
)
from common.alarm_registry import _METRIC_DISPLAY
from daily_monitor.lambda_handler import _classify_alarm


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

_RESOURCE_TYPES = [
    "EC2", "RDS", "ALB", "NLB", "TG",
    "AuroraRDS", "DocDB", "ElastiCache", "NAT",
]

resource_type_st = st.sampled_from(_RESOURCE_TYPES)
metric_st = st.sampled_from(list(_METRIC_DISPLAY.keys()))
threshold_st = st.floats(
    min_value=0.01, max_value=999999.0,
    allow_nan=False, allow_infinity=False,
)
simple_id_st = st.from_regex(r"[a-z]{1,5}-[a-z0-9]{4,12}", fullmatch=True)

alb_arn_st = st.builds(
    lambda n, h: (
        f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
        f":loadbalancer/app/{n}/{h}"
    ),
    n=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

nlb_arn_st = st.builds(
    lambda n, h: (
        f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
        f":loadbalancer/net/{n}/{h}"
    ),
    n=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

tg_arn_st = st.builds(
    lambda n, h: (
        f"arn:aws:elasticloadbalancing:us-east-1:123456789012"
        f":targetgroup/{n}/{h}"
    ),
    n=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

resource_name_st = st.from_regex(r"[a-z][a-z0-9\-]{2,20}", fullmatch=True)


def _resource_id_for_type(resource_type: str):
    if resource_type == "ALB":
        return alb_arn_st
    if resource_type == "NLB":
        return nlb_arn_st
    if resource_type == "TG":
        return tg_arn_st
    return simple_id_st


# ──────────────────────────────────────────────
# Property 2a: Truncate preservation — 255자 제한 및 truncate 순서
# Validates: Requirements 3.1
# ──────────────────────────────────────────────

class TestTruncatePreservation:
    """_pretty_alarm_name() 출력이 항상 255자 이하이고,
    truncate 시 label이 먼저 줄어든 후 display_metric이 줄어드는지 검증."""

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        threshold=threshold_st,
        data=st.data(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_output_never_exceeds_255_chars(
        self, resource_type, metric, threshold, data,
    ):
        """
        **Validates: Requirements 3.1**

        For all inputs, len(_pretty_alarm_name(...)) <= 255.
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))
        resource_name = data.draw(resource_name_st)

        result = _pretty_alarm_name(
            resource_type, resource_id, resource_name,
            metric, threshold,
        )

        assert len(result) <= 255, (
            f"Alarm name length {len(result)} exceeds 255: {result!r}"
        )

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        threshold=threshold_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_truncate_order_label_first(
        self, resource_type, metric, threshold, data,
    ):
        """
        **Validates: Requirements 3.1**

        When the untruncated name would exceed 255 chars,
        label is truncated first (contains '...') while
        display_metric is preserved if possible.
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))

        # Build a label long enough to guarantee truncation:
        # fixed parts consume ~40-60 chars, so 250-char label forces it
        long_label = "a" * 250

        result = _pretty_alarm_name(
            resource_type, resource_id, long_label,
            metric, threshold,
        )

        assert len(result) <= 255, (
            f"Alarm name length {len(result)} exceeds 255"
        )
        # Label must be truncated → "..." marker present
        assert "..." in result, (
            f"Expected truncation marker '...' for 250-char label"
        )
        # display_metric should be preserved (not truncated)
        # when only label truncation is needed
        display_name = _METRIC_DISPLAY.get(
            metric.split("-")[0] if metric.startswith("Disk-") else metric,
            ("unknown", ">", ""),
        )[0]
        assert display_name in result, (
            f"display_metric '{display_name}' should be preserved "
            f"when only label is truncated: {result!r}"
        )


# ──────────────────────────────────────────────
# Property 2b: Short_ID preservation — ALB/NLB/TG suffix uses {name}/{hash}
# Validates: Requirements 3.2
# ──────────────────────────────────────────────

class TestShortIDPreservation:
    """ALB/NLB/TG ARN 입력 시 suffix에 Short_ID({name}/{hash})가 사용되는지 검증."""

    @given(
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_alb_suffix_uses_short_id(
        self, metric, threshold, resource_name, data,
    ):
        """
        **Validates: Requirements 3.2**

        For ALB ARN inputs, suffix contains Short_ID {name}/{hash},
        not the full ARN.
        """
        arn = data.draw(alb_arn_st)
        short_id = _shorten_elb_resource_id(arn, "ALB")

        result = _pretty_alarm_name(
            "ALB", arn, resource_name, metric, threshold,
        )

        # Short_ID must appear in the suffix (inside parentheses)
        assert f"({short_id})" in result or f"(TagName: {short_id})" in result, (
            f"ALB alarm name should contain Short_ID '{short_id}' "
            f"in suffix, got: {result!r}"
        )
        # Full ARN must NOT appear in the alarm name
        assert arn not in result, (
            f"Full ARN should not appear in alarm name: {result!r}"
        )
        # Short_ID must be {name}/{hash} format
        assert "/" in short_id, (
            f"Short_ID should contain '/' separator: {short_id!r}"
        )

    @given(
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_nlb_suffix_uses_short_id(
        self, metric, threshold, resource_name, data,
    ):
        """
        **Validates: Requirements 3.2**

        For NLB ARN inputs, suffix contains Short_ID {name}/{hash}.
        """
        arn = data.draw(nlb_arn_st)
        short_id = _shorten_elb_resource_id(arn, "NLB")

        result = _pretty_alarm_name(
            "NLB", arn, resource_name, metric, threshold,
        )

        assert f"({short_id})" in result or f"(TagName: {short_id})" in result, (
            f"NLB alarm name should contain Short_ID '{short_id}' "
            f"in suffix, got: {result!r}"
        )
        assert arn not in result
        assert "/" in short_id

    @given(
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_tg_suffix_uses_short_id(
        self, metric, threshold, resource_name, data,
    ):
        """
        **Validates: Requirements 3.2**

        For TG ARN inputs, suffix contains Short_ID {name}/{hash}.
        """
        arn = data.draw(tg_arn_st)
        short_id = _shorten_elb_resource_id(arn, "TG")

        result = _pretty_alarm_name(
            "TG", arn, resource_name, metric, threshold,
        )

        assert f"({short_id})" in result or f"(TagName: {short_id})" in result, (
            f"TG alarm name should contain Short_ID '{short_id}' "
            f"in suffix, got: {result!r}"
        )
        assert arn not in result
        assert "/" in short_id


# ──────────────────────────────────────────────
# Property 2c: resource_type parsing preservation
# Validates: Requirements 3.4
# ──────────────────────────────────────────────

class TestResourceTypeParsingPreservation:
    """_classify_alarm()이 새 포맷 알람 이름에서 resource_type을
    올바르게 추출하는지 검증."""

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_classify_extracts_resource_type(
        self, resource_type, metric, threshold, resource_name, data,
    ):
        """
        **Validates: Requirements 3.4**

        _classify_alarm() extracts [EC2], [RDS] etc. correctly
        from alarm names generated by _pretty_alarm_name().
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))

        alarm_name = _pretty_alarm_name(
            resource_type, resource_id, resource_name,
            metric, threshold,
        )

        result: dict[str, dict[str, list[str]]] = {}
        _classify_alarm(alarm_name, result)

        assert resource_type in result, (
            f"_classify_alarm should extract resource_type "
            f"'{resource_type}' from '{alarm_name}', "
            f"got keys: {list(result.keys())}"
        )


# ──────────────────────────────────────────────
# Property 2d: AlarmDescription preservation
# Validates: Requirements 3.5
# ──────────────────────────────────────────────

class TestAlarmDescriptionPreservation:
    """_build_alarm_description()이 resource_id 필드에
    전체 ARN/ID를 변경 없이 저장하는지 검증."""

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        data=st.data(),
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_description_stores_full_resource_id(
        self, resource_type, metric, data,
    ):
        """
        **Validates: Requirements 3.5**

        _build_alarm_description() stores the full ARN/ID
        in the resource_id field unchanged.
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))

        desc = _build_alarm_description(
            resource_type, resource_id, metric,
        )

        # The full resource_id must appear in the description JSON
        assert resource_id in desc, (
            f"Full resource_id '{resource_id}' should appear in "
            f"AlarmDescription, got: {desc!r}"
        )
        # Verify it's in the JSON metadata portion
        assert f'"resource_id":"{resource_id}"' in desc, (
            f"resource_id field should contain full ID in JSON, "
            f"got: {desc!r}"
        )
