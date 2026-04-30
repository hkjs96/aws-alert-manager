"""
alarm_naming PBT — Correctness Properties

Property 1: 생성된 알람 이름이 255자 이하
Property 2: _build_alarm_description / _parse_alarm_metadata 라운드트립
Property 3: _shorten_elb_resource_id — ALB/NLB/TG Short_ID가 원본 ARN의 부분 문자열
Property 4: truncate 시 '...' 접미사 + TagName 보존
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.alarm_naming import (
    _pretty_alarm_name,
    _build_alarm_description,
    _parse_alarm_metadata,
    _shorten_elb_resource_id,
)
from common.alarm_registry import _METRIC_DISPLAY

_METRICS = list(_METRIC_DISPLAY.keys())
_RESOURCE_TYPES = ["EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS", "Lambda"]

# 알람 이름에 허용되는 resource_id 문자 (알파벳·숫자·하이픈·밑줄)
_safe_id = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=50,
)
_safe_text = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ",
    min_size=0,
    max_size=250,
)
_threshold = st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)


# ──────────────────────────────────────────────────────────────
# Property 1: 알람 이름이 항상 255자 이하
# ──────────────────────────────────────────────────────────────
@given(
    resource_type=st.sampled_from(_RESOURCE_TYPES),
    resource_id=_safe_id,
    resource_name=_safe_text,
    metric=st.sampled_from(_METRICS),
    threshold=_threshold,
)
@settings(max_examples=200)
def test_property1_alarm_name_length_under_255(
    resource_type, resource_id, resource_name, metric, threshold
):
    name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)
    assert len(name) <= 255, f"이름 길이 {len(name)} 초과: {name!r}"


# ──────────────────────────────────────────────────────────────
# Property 2: build_alarm_description / parse_alarm_metadata 라운드트립
# metric_key, resource_id, resource_type가 손실 없이 복원됨
# ──────────────────────────────────────────────────────────────
@given(
    resource_type=st.sampled_from(_RESOURCE_TYPES),
    resource_id=_safe_id,
    metric_key=st.sampled_from(_METRICS),
    human_prefix=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ",
        min_size=0,
        max_size=200,
    ),
)
@settings(max_examples=200)
def test_property2_description_roundtrip(resource_type, resource_id, metric_key, human_prefix):
    desc = _build_alarm_description(resource_type, resource_id, metric_key, human_prefix)
    parsed = _parse_alarm_metadata(desc)

    assert parsed is not None, f"파싱 실패: {desc!r}"
    assert parsed["resource_type"] == resource_type
    assert parsed["resource_id"] == resource_id
    assert parsed["metric_key"] == metric_key


# ──────────────────────────────────────────────────────────────
# Property 3: ALB/NLB/TG Short_ID가 원본 ARN의 부분 문자열
# ──────────────────────────────────────────────────────────────

_lb_name = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)
_lb_hash = st.text(alphabet="0123456789abcdef", min_size=16, max_size=16)


@given(lb_name=_lb_name, lb_hash=_lb_hash)
@settings(max_examples=100)
def test_property3_alb_short_id_is_substring(lb_name, lb_hash):
    arn = f"arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/{lb_name}/{lb_hash}"
    short = _shorten_elb_resource_id(arn, "ALB")
    assert short in arn, f"Short_ID {short!r}가 원본 ARN에 없음"
    assert short == f"{lb_name}/{lb_hash}"


@given(lb_name=_lb_name, lb_hash=_lb_hash)
@settings(max_examples=100)
def test_property3_nlb_short_id_is_substring(lb_name, lb_hash):
    arn = f"arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/net/{lb_name}/{lb_hash}"
    short = _shorten_elb_resource_id(arn, "NLB")
    assert short in arn, f"Short_ID {short!r}가 원본 ARN에 없음"
    assert short == f"{lb_name}/{lb_hash}"


@given(tg_name=_lb_name, tg_hash=_lb_hash)
@settings(max_examples=100)
def test_property3_tg_short_id_is_substring(tg_name, tg_hash):
    arn = f"arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:targetgroup/{tg_name}/{tg_hash}"
    short = _shorten_elb_resource_id(arn, "TG")
    assert short in arn, f"Short_ID {short!r}가 원본 ARN에 없음"
    assert short == f"{tg_name}/{tg_hash}"


@given(resource_id=_safe_id)
@settings(max_examples=100)
def test_property3_non_lb_returns_unchanged(resource_id):
    for rtype in ("EC2", "RDS", "Lambda"):
        short = _shorten_elb_resource_id(resource_id, rtype)
        assert short == resource_id, f"{rtype}: {short!r} != {resource_id!r}"


# ──────────────────────────────────────────────────────────────
# Property 4: 이름이 truncate될 때 '...' 포함 + TagName 보존
# ──────────────────────────────────────────────────────────────
@given(
    resource_type=st.sampled_from(_RESOURCE_TYPES),
    resource_id=_safe_id,
    resource_name=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=200,
        max_size=250,
    ),
    metric=st.sampled_from(_METRICS),
    threshold=_threshold,
)
@settings(max_examples=100)
def test_property4_truncated_name_contains_ellipsis_and_tagname(
    resource_type, resource_id, resource_name, metric, threshold
):
    name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric, threshold)
    assert len(name) <= 255

    # 잘린 경우 '...'와 TagName 접미사 보존
    if len(name) < len(resource_name) + 10:
        assert "..." in name, f"truncate됐는데 '...' 없음: {name!r}"

    # TagName 부분은 항상 존재
    assert "(TagName:" in name, f"TagName 누락: {name!r}"
