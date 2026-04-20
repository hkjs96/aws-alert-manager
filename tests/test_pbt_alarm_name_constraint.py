"""
Property 5: 알람 이름 255자 제한 준수

_pretty_alarm_name()이 어떤 입력에 대해서도 항상 255자 이하를 반환하는지 검증.
hypothesis로 다양한 길이의 resource_type, resource_id, label, metric, threshold 생성.

**Validates: CloudWatch PutMetricAlarm API AlarmName 제약**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import _pretty_alarm_name, _METRIC_DISPLAY, _shorten_elb_resource_id


# ──────────────────────────────────────────────
# Hypothesis 전략
# ──────────────────────────────────────────────

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])

# resource_id: 짧은 EC2 ID부터 긴 ELB ARN까지
resource_ids = st.one_of(
    # EC2 style: i-0abc123def456789a (19 chars)
    st.from_regex(r"i-[0-9a-f]{17}", fullmatch=True),
    # RDS style: db-xxx (variable)
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=3,
        max_size=63,
    ).map(lambda s: f"db-{s}"),
    # ALB ARN style
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=3,
        max_size=60,
    ).map(lambda s: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/{s}/1234567890abcdef"),
    # NLB ARN style
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=3,
        max_size=60,
    ).map(lambda s: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/{s}/1234567890abcdef"),
    # TG ARN style
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=3,
        max_size=60,
    ).map(lambda s: f"arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/{s}/1234567890abcdef"),
)

# resource_name (label): 빈 문자열부터 매우 긴 이름까지
resource_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_ ",
    ),
    min_size=0,
    max_size=256,
)

# 메트릭 키: 하드코딩 + 동적 (긴 이름 포함)
metric_keys = st.one_of(
    st.sampled_from([
        "CPU", "Memory", "Disk-root", "Disk-data",
        "FreeMemoryGB", "FreeStorageGB", "Connections",
        "RequestCount",
    ]),
    # 동적 메트릭: 최대 118자 (태그 키 128자 - Threshold_ 10자)
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="-_.",
        ),
        min_size=1,
        max_size=118,
    ),
)

# 임계치: 다양한 범위
thresholds = st.floats(
    min_value=0.01,
    max_value=9999999.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda x: round(x, 2))


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestAlarmNameConstraint:
    """
    _pretty_alarm_name()이 어떤 입력에 대해서도 항상 255자 이하를 반환하는지 검증.

    **Validates: CloudWatch PutMetricAlarm API AlarmName 제약**
    """

    @given(
        resource_type=resource_types,
        resource_id=resource_ids,
        resource_name=resource_names,
        metric=metric_keys,
        threshold=thresholds,
    )
    @settings(max_examples=20, deadline=None)
    def test_alarm_name_never_exceeds_255_chars(
        self, resource_type, resource_id, resource_name, metric, threshold,
    ):
        """
        **Property 5: 알람 이름 255자 제한** - 항상 255자 이하

        임의의 resource_type, resource_id, resource_name, metric, threshold
        조합에 대해 _pretty_alarm_name()이 반환하는 알람 이름이
        항상 255자 이하여야 한다.

        **Validates: CloudWatch PutMetricAlarm API AlarmName 제약**
        """
        name = _pretty_alarm_name(
            resource_type, resource_id, resource_name, metric, threshold,
        )

        assert len(name) <= 255, (
            f"Alarm name exceeds 255 chars: len={len(name)}\n"
            f"name={name!r}\n"
            f"inputs: resource_type={resource_type!r}, "
            f"resource_id={resource_id!r} (len={len(resource_id)}), "
            f"resource_name={resource_name!r} (len={len(resource_name)}), "
            f"metric={metric!r} (len={len(metric)}), "
            f"threshold={threshold}"
        )

    @given(
        resource_type=resource_types,
        resource_id=resource_ids,
        resource_name=resource_names,
        metric=metric_keys,
        threshold=thresholds,
    )
    @settings(max_examples=20, deadline=None)
    def test_alarm_name_preserves_resource_id(
        self, resource_type, resource_id, resource_name, metric, threshold,
    ):
        """
        **Property 5: resource_id 보존** - truncate 시에도 resource_id 유지

        알람 이름이 truncate되더라도 resource_id 부분은 항상 보존되어야 한다.
        알람 검색/매칭에 resource_id가 필수이기 때문이다.

        **Validates: CloudWatch PutMetricAlarm API AlarmName 제약**
        """
        name = _pretty_alarm_name(
            resource_type, resource_id, resource_name, metric, threshold,
        )

        # ALB/NLB/TG는 Short_ID suffix, EC2/RDS는 원본 resource_id suffix
        expected_suffix = _shorten_elb_resource_id(resource_id, resource_type)
        assert name.endswith(f"(TagName: {expected_suffix})"), (
            f"Alarm name does not end with (TagName: {expected_suffix})\n"
            f"name={name!r}"
        )
