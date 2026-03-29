"""
Property Tests — ELB Resource Type Split

Property 3: 알람 이름 255자 제한 (ALB/NLB/TG 포함)
Property 6: ARN suffix 디멘션 추출 일관성

**Validates: Requirements 1.2, 2.2, 3.2, 4.4, 6.1, 6.2**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from common.alarm_manager import _pretty_alarm_name
from common.alarm_naming import _shorten_elb_resource_id
from common.dimension_builder import _extract_elb_dimension, _resolve_tg_namespace
from common.alarm_registry import _get_alarm_defs


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

lb_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-"),
    min_size=3, max_size=32,
)
hashes = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

resource_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_ "),
    min_size=0, max_size=50,
)

thresholds = st.floats(min_value=0.1, max_value=9999.0, allow_nan=False, allow_infinity=False)
lb_types = st.sampled_from(["network", "application", ""])


@st.composite
def alb_arns(draw):
    name = draw(lb_names)
    h = draw(hashes)
    return f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/{name}/{h}"


@st.composite
def nlb_arns(draw):
    name = draw(lb_names)
    h = draw(hashes)
    return f"arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/{name}/{h}"


@st.composite
def tg_arns(draw):
    name = draw(lb_names)
    h = draw(hashes)
    return f"arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/{name}/{h}"


elb_type_and_arn = st.one_of(
    alb_arns().map(lambda a: ("ALB", a)),
    nlb_arns().map(lambda a: ("NLB", a)),
    tg_arns().map(lambda a: ("TG", a)),
)


# ──────────────────────────────────────────────
# Property 3: 알람 이름 prefix와 resource_type 일치
# ──────────────────────────────────────────────

@given(data=elb_type_and_arn, name=resource_names, threshold=thresholds)
@settings(max_examples=30, deadline=None)
def test_alarm_name_prefix_matches_resource_type(data, name, threshold):
    """알람 이름이 [{resource_type}] 으로 시작한다."""
    rtype, arn = data
    alarm_name = _pretty_alarm_name(rtype, arn, name, "CPU", threshold)
    assert alarm_name.startswith(f"[{rtype}] "), (
        f"Expected prefix [{rtype}], got: {alarm_name[:20]}"
    )


@given(data=elb_type_and_arn, name=resource_names, threshold=thresholds)
@settings(max_examples=30, deadline=None)
def test_alarm_name_ends_with_short_id(data, name, threshold):
    """ALB/NLB/TG 알람 이름이 Short_ID suffix로 끝난다."""
    rtype, arn = data
    alarm_name = _pretty_alarm_name(rtype, arn, name, "CPU", threshold)
    short_id = _shorten_elb_resource_id(arn, rtype)
    assert alarm_name.endswith(f"({short_id})"), (
        f"Expected suffix ({short_id}), got: ...{alarm_name[-50:]}"
    )


# ──────────────────────────────────────────────
# Property 6: ARN suffix 디멘션 추출 일관성
# ──────────────────────────────────────────────

@given(arn=alb_arns())
@settings(max_examples=30)
def test_alb_dimension_starts_with_app(arn):
    """ALB 디멘션 값이 app/ 으로 시작한다."""
    dim = _extract_elb_dimension(arn)
    assert dim.startswith("app/"), f"Expected app/ prefix, got: {dim}"


@given(arn=nlb_arns())
@settings(max_examples=30)
def test_nlb_dimension_starts_with_net(arn):
    """NLB 디멘션 값이 net/ 으로 시작한다."""
    dim = _extract_elb_dimension(arn)
    assert dim.startswith("net/"), f"Expected net/ prefix, got: {dim}"


@given(arn=tg_arns())
@settings(max_examples=30)
def test_tg_dimension_starts_with_targetgroup(arn):
    """TG 디멘션 값이 targetgroup/ 으로 시작한다."""
    dim = _extract_elb_dimension(arn)
    assert dim.startswith("targetgroup/"), f"Expected targetgroup/ prefix, got: {dim}"


@given(data=elb_type_and_arn)
@settings(max_examples=30)
def test_short_id_differs_from_dimension(data):
    """Short_ID와 Dimension 값은 다르다 (ALB/NLB만)."""
    rtype, arn = data
    if rtype == "TG":
        return  # TG는 Short_ID와 Dimension이 같을 수 있음
    short_id = _shorten_elb_resource_id(arn, rtype)
    dim = _extract_elb_dimension(arn)
    assert short_id != dim, f"Short_ID == Dimension: {short_id}"


# ──────────────────────────────────────────────
# Property 4: TG 네임스페이스 동적 결정
# ──────────────────────────────────────────────

@given(lb_type=lb_types)
@settings(max_examples=10)
def test_tg_namespace_resolution(lb_type):
    """_lb_type에 따라 TG 네임스페이스가 올바르게 결정된다."""
    alarm_def = {"namespace": "AWS/ApplicationELB"}
    tags = {"_lb_type": lb_type} if lb_type else {}
    ns = _resolve_tg_namespace(alarm_def, tags)
    if lb_type == "network":
        assert ns == "AWS/NetworkELB"
    else:
        assert ns == "AWS/ApplicationELB"
