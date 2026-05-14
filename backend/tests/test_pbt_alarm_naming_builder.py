"""
alarm_naming PBT — Requirements 1.2 (Roadmap Phase 1)

Property 1: 생성된 이름이 255자 이하 (알람 이름 규칙 §6)
Property 2: truncate 시 "..." 접미사 존재, suffix(TagName) 보존
Property 3: _shorten_elb_resource_id ALB/NLB/TG Short_ID 라운드트립
Property 4: AlarmDescription에 metric_key, resource_id, resource_type 포함
"""

import json

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ──────────────────────────────────────────────
# 전략
# ──────────────────────────────────────────────

safe_text = st.text(
    min_size=1,
    max_size=120,
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
)

thresholds = st.one_of(
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=0, max_value=1_000_000).map(float),
)

resource_types_all = st.sampled_from([
    "EC2", "RDS", "ALB", "NLB", "TG", "VPN", "ECS", "SQS", "EFS", "Lambda",
])


# ──────────────────────────────────────────────
# Property 1: 알람 이름이 255자 이하
# ──────────────────────────────────────────────

class TestAlarmNameLengthConstraint:
    @given(
        resource_type=resource_types_all,
        resource_id=safe_text,
        resource_name=st.one_of(st.just(""), safe_text),
        metric=st.sampled_from(["CPU", "Memory", "Disk-root", "FreeMemoryGB", "ELB5XX"]),
        threshold=thresholds,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_알람_이름은_항상_255자_이하(
        self, resource_type, resource_id, resource_name, metric, threshold
    ):
        from common.alarm_naming import _pretty_alarm_name

        name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)
        assert len(name) <= 255


# ──────────────────────────────────────────────
# Property 2: truncate 시 "..." 포함 + suffix 보존
# ──────────────────────────────────────────────

class TestAlarmNameTruncation:
    @given(
        label=st.text(min_size=200, max_size=300, alphabet="abcdefghijklmnopqrstuvwxyz-"),
        threshold=thresholds,
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_truncate_발생_시_ellipsis_포함(self, label, threshold):
        """이름이 잘릴 때 '...' 접미사가 반드시 포함되어야 한다."""
        from common.alarm_naming import _pretty_alarm_name

        name = _pretty_alarm_name("EC2", "i-0abcdef1234567890", label, "CPU", threshold)

        # truncate 발생 조건: label이 충분히 길면 "..."가 포함되어야 함
        if len(name) == 255:
            assert "..." in name

    @given(
        resource_id=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"),
        resource_type=resource_types_all,
        label=st.text(min_size=200, max_size=300, alphabet="abcdefghijklmnopqrstuvwxyz-"),
        threshold=thresholds,
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_suffix_TagName이_항상_보존된다(
        self, resource_id, resource_type, label, threshold
    ):
        """TagName suffix '(TagName: ...)' 는 절대 잘리지 않아야 한다."""
        from common.alarm_naming import _pretty_alarm_name

        name = _pretty_alarm_name(resource_type, resource_id, label, "CPU", threshold)

        assert "(TagName:" in name, f"suffix 누락: {name!r}"


# ──────────────────────────────────────────────
# Property 3: _shorten_elb_resource_id Short_ID
# ──────────────────────────────────────────────

class TestShortenElbResourceId:
    @given(
        name=st.text(min_size=1, max_size=32, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"),
        hash_part=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_ALB_ARN에서_Short_ID_추출(self, name, hash_part):
        """ALB ARN에서 '{name}/{hash}' 형태의 Short_ID를 추출해야 한다."""
        from common.alarm_naming import _shorten_elb_resource_id

        arn = f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/{name}/{hash_part}"
        short_id = _shorten_elb_resource_id(arn, "ALB")

        assert short_id == f"{name}/{hash_part}"

    @given(
        name=st.text(min_size=1, max_size=32, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"),
        hash_part=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_NLB_ARN에서_Short_ID_추출(self, name, hash_part):
        """NLB ARN에서 '{name}/{hash}' 형태의 Short_ID를 추출해야 한다."""
        from common.alarm_naming import _shorten_elb_resource_id

        arn = f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/{name}/{hash_part}"
        short_id = _shorten_elb_resource_id(arn, "NLB")

        assert short_id == f"{name}/{hash_part}"

    @given(
        name=st.text(min_size=1, max_size=32, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"),
        hash_part=st.from_regex(r"[0-9a-f]{16}", fullmatch=True),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_TG_ARN에서_Short_ID_추출(self, name, hash_part):
        """TG ARN에서 '{name}/{hash}' 형태의 Short_ID를 추출해야 한다."""
        from common.alarm_naming import _shorten_elb_resource_id

        arn = f"arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/{name}/{hash_part}"
        short_id = _shorten_elb_resource_id(arn, "TG")

        assert short_id == f"{name}/{hash_part}"

    @given(
        resource_id=safe_text,
        resource_type=st.sampled_from(["EC2", "RDS", "VPN", "Lambda"]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_비ELB_타입은_resource_id_그대로_반환(self, resource_id, resource_type):
        """ALB/NLB/TG가 아닌 타입은 resource_id를 변환 없이 반환해야 한다."""
        from common.alarm_naming import _shorten_elb_resource_id

        result = _shorten_elb_resource_id(resource_id, resource_type)
        assert result == resource_id


# ──────────────────────────────────────────────
# Property 4: AlarmDescription 메타데이터 포함
# ──────────────────────────────────────────────

class TestBuildAlarmDescription:
    @given(
        resource_type=resource_types_all,
        resource_id=safe_text,
        metric_key=st.sampled_from(["CPU", "Memory", "Disk", "FreeMemoryGB", "Connections"]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_AlarmDescription에_메타데이터_JSON이_포함된다(
        self, resource_type, resource_id, metric_key
    ):
        """AlarmDescription에 metric_key, resource_id, resource_type이 JSON으로 포함되어야 한다.

        human_prefix 있을 때: "{prefix} | {json}"
        human_prefix 없을 때: "{json}" (구분자 없음)
        """
        from common.alarm_naming import _build_alarm_description

        human_prefix = f"Auto-created for {resource_type} {resource_id}"
        desc = _build_alarm_description(resource_type, resource_id, metric_key, human_prefix)
        # " | {json}" 형태의 메타데이터 파싱
        parts = desc.rsplit(" | ", 1)
        assert len(parts) == 2, f"'|' 구분자 없음: {desc!r}"

        metadata = json.loads(parts[1])
        assert metadata["metric_key"] == metric_key
        assert metadata["resource_id"] == resource_id
        assert metadata["resource_type"] == resource_type

    @given(
        resource_type=resource_types_all,
        resource_id=safe_text,
        metric_key=safe_text,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_AlarmDescription이_1024자_이하(
        self, resource_type, resource_id, metric_key
    ):
        """AlarmDescription은 CloudWatch API 제한인 1024자 이하여야 한다."""
        from common.alarm_naming import _build_alarm_description

        desc = _build_alarm_description(resource_type, resource_id, metric_key)
        assert len(desc) <= 1024
