"""
Bug Condition Exploration Test — 알람 이름 포맷 direction-threshold 공백 및 TagName: 접두사 누락

Property 1 (Bug Condition): _pretty_alarm_name()이 생성하는 알람 이름에서
direction과 threshold 사이에 공백이 없고 (예: >=80 대신 >= 80),
suffix에 TagName: 접두사가 없다 (예: (i-abc) 대신 (TagName: i-abc)).

Bug Condition: isBugCondition(input) where
  alarmName contains "{direction}{threshold}" (no space)
  OR alarmName suffix matches "({short_id})" (no TagName: prefix)

**Validates: Requirements 1.1, 1.2**

EXPECTED: These tests FAIL on unfixed code because:
- threshold_part = f" {direction}{thr_str}{unit} " (no space after direction)
- suffix = f"({short_id})" (no TagName: prefix)
"""

import re

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from common.alarm_naming import _pretty_alarm_name, _shorten_elb_resource_id
from common.alarm_registry import _METRIC_DISPLAY


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

_RESOURCE_TYPES = ["EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS", "DocDB", "ElastiCache", "NAT"]

resource_type_st = st.sampled_from(_RESOURCE_TYPES)

# Metric keys from _METRIC_DISPLAY (excluding Disk- variants for simplicity)
metric_st = st.sampled_from(list(_METRIC_DISPLAY.keys()))

# Positive float thresholds (realistic range)
threshold_st = st.floats(min_value=0.01, max_value=999999.0, allow_nan=False, allow_infinity=False)

# Resource IDs: simple IDs for non-ELB, ARN-like for ELB types
simple_id_st = st.from_regex(r"[a-z]{1,5}-[a-z0-9]{4,12}", fullmatch=True)

alb_arn_st = st.builds(
    lambda name, h: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/{name}/{h}",
    name=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

nlb_arn_st = st.builds(
    lambda name, h: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/{name}/{h}",
    name=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

tg_arn_st = st.builds(
    lambda name, h: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/{name}/{h}",
    name=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    h=st.from_regex(r"[a-f0-9]{16}", fullmatch=True),
)

resource_name_st = st.from_regex(r"[a-z][a-z0-9\-]{2,20}", fullmatch=True)


def _resource_id_for_type(resource_type: str):
    """Return an appropriate resource_id strategy for the given resource_type."""
    if resource_type == "ALB":
        return alb_arn_st
    elif resource_type == "NLB":
        return nlb_arn_st
    elif resource_type == "TG":
        return tg_arn_st
    else:
        return simple_id_st


# ──────────────────────────────────────────────
# Property 1a: direction-threshold 공백 검증
# Validates: Requirements 1.1, 2.1
# ──────────────────────────────────────────────

class TestBugConditionDirectionThresholdSpace:
    """_pretty_alarm_name() 출력에서 direction과 threshold 사이에 공백이 있어야 한다.

    BUG: 현재 코드는 threshold_part = f" {direction}{thr_str}{unit} "로
    direction과 threshold 사이에 공백이 없다.
    """

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_direction_threshold_has_space(self, resource_type, metric, threshold, resource_name, data):
        """
        **Validates: Requirements 1.1, 2.1**

        For any valid inputs, _pretty_alarm_name() output must contain
        a space between direction and threshold: "{direction} {threshold}".
        This FAILS on unfixed code (proves the bug exists).
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))

        result = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)

        # Determine expected direction and threshold string
        direction = _METRIC_DISPLAY[metric][1]
        if threshold == int(threshold):
            thr_str = str(int(threshold))
        else:
            thr_str = f"{threshold:g}"

        # The output must contain "{direction} {thr_str}" (with space)
        expected_pattern = f"{direction} {thr_str}"
        assert expected_pattern in result, (
            f"_pretty_alarm_name({resource_type!r}, ..., {metric!r}, {threshold}) "
            f"produced '{result}' which does not contain '{expected_pattern}' "
            f"(space between direction and threshold is missing)"
        )


# ──────────────────────────────────────────────
# Property 1b: suffix TagName: 접두사 검증
# Validates: Requirements 1.2, 2.2
# ──────────────────────────────────────────────

class TestBugConditionSuffixTagName:
    """_pretty_alarm_name() 출력의 suffix가 (TagName: {short_id}) 포맷이어야 한다.

    BUG: 현재 코드는 suffix = f"({short_id})"로 TagName: 접두사가 없다.
    """

    @given(
        resource_type=resource_type_st,
        metric=metric_st,
        threshold=threshold_st,
        resource_name=resource_name_st,
        data=st.data(),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_suffix_has_tagname_prefix(self, resource_type, metric, threshold, resource_name, data):
        """
        **Validates: Requirements 1.2, 2.2**

        For any valid inputs, _pretty_alarm_name() output must end with
        suffix "(TagName: {short_id})".
        This FAILS on unfixed code (proves the bug exists).
        """
        resource_id = data.draw(_resource_id_for_type(resource_type))

        result = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)

        short_id = _shorten_elb_resource_id(resource_id, resource_type)
        expected_suffix = f"(TagName: {short_id})"

        assert result.endswith(expected_suffix), (
            f"_pretty_alarm_name({resource_type!r}, {resource_id!r}, ..., {metric!r}, {threshold}) "
            f"produced '{result}' which does not end with '{expected_suffix}' "
            f"(TagName: prefix is missing in suffix)"
        )
