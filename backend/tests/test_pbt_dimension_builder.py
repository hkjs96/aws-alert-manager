"""
dimension_builder PBT — Requirements 1.3 (Roadmap Phase 1)

Property 1: ALB LB-레벨 메트릭 디멘션에 TargetGroup 없음 (LoadBalancer 단일)
Property 2: TG 메트릭 디멘션에 항상 LoadBalancer가 포함됨
Property 3: CloudFront 디멘션에 항상 Region=Global 포함
Property 4: _extract_elb_dimension은 ARN과 Short_ID 구분
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ──────────────────────────────────────────────
# 전략
# ──────────────────────────────────────────────

safe_name = st.text(
    min_size=1, max_size=32,
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
)
hash_part = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)
account_id = st.from_regex(r"[0-9]{12}", fullmatch=True)
region = st.sampled_from(["us-east-1", "ap-northeast-2", "eu-west-1"])


def alb_arn_strategy():
    return st.builds(
        lambda name, h, acct, r: f"arn:aws:elasticloadbalancing:{r}:{acct}:loadbalancer/app/{name}/{h}",
        name=safe_name, h=hash_part, acct=account_id, r=region,
    )


def nlb_arn_strategy():
    return st.builds(
        lambda name, h, acct, r: f"arn:aws:elasticloadbalancing:{r}:{acct}:loadbalancer/net/{name}/{h}",
        name=safe_name, h=hash_part, acct=account_id, r=region,
    )


def tg_arn_strategy():
    return st.builds(
        lambda name, h, acct, r: f"arn:aws:elasticloadbalancing:{r}:{acct}:targetgroup/{name}/{h}",
        name=safe_name, h=hash_part, acct=account_id, r=region,
    )


# ──────────────────────────────────────────────
# Property 1: ALB 디멘션에 TargetGroup 없음
# ──────────────────────────────────────────────

class TestALBDimensionNoTargetGroup:
    @given(alb_arn=alb_arn_strategy())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_ALB_디멘션에_TargetGroup_없음(self, alb_arn):
        """ALB LB-레벨 알람의 디멘션에 TargetGroup이 포함되어선 안 된다."""
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "LoadBalancer"}
        dims = _build_dimensions(alarm_def, alb_arn, "ALB", {})

        dim_names = [d["Name"] for d in dims]
        assert "TargetGroup" not in dim_names, (
            f"ALB 디멘션에 TargetGroup이 포함됨: {dims}"
        )
        assert "LoadBalancer" in dim_names

    @given(nlb_arn=nlb_arn_strategy())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_NLB_디멘션에_TargetGroup_없음(self, nlb_arn):
        """NLB LB-레벨 알람의 디멘션에 TargetGroup이 포함되어선 안 된다."""
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "LoadBalancer"}
        dims = _build_dimensions(alarm_def, nlb_arn, "NLB", {})

        dim_names = [d["Name"] for d in dims]
        assert "TargetGroup" not in dim_names
        assert "LoadBalancer" in dim_names


# ──────────────────────────────────────────────
# Property 2: TG 디멘션에 항상 LoadBalancer 포함
# ──────────────────────────────────────────────

class TestTGDimensionHasLoadBalancer:
    @given(
        tg_arn=tg_arn_strategy(),
        lb_arn=alb_arn_strategy(),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_TG_디멘션에_항상_LoadBalancer_포함(self, tg_arn, lb_arn):
        """TG 알람의 디멘션에 LoadBalancer가 항상 포함되어야 한다 (복합 디멘션 필수)."""
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "TargetGroup"}
        resource_tags = {"_lb_arn": lb_arn}
        dims = _build_dimensions(alarm_def, tg_arn, "TG", resource_tags)

        dim_names = [d["Name"] for d in dims]
        assert "TargetGroup" in dim_names, f"TargetGroup 없음: {dims}"
        assert "LoadBalancer" in dim_names, f"LoadBalancer 없음: {dims}"

    @given(
        tg_arn=tg_arn_strategy(),
        lb_arn=nlb_arn_strategy(),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_NLB_TG_디멘션에도_LoadBalancer_포함(self, tg_arn, lb_arn):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "TargetGroup"}
        resource_tags = {"_lb_arn": lb_arn, "_lb_type": "network"}
        dims = _build_dimensions(alarm_def, tg_arn, "TG", resource_tags)

        dim_names = [d["Name"] for d in dims]
        assert "TargetGroup" in dim_names
        assert "LoadBalancer" in dim_names


# ──────────────────────────────────────────────
# Property 3: CloudFront 디멘션에 Region=Global 포함
# ──────────────────────────────────────────────

class TestCloudFrontDimensionRegionGlobal:
    @given(
        distribution_id=st.from_regex(r"[A-Z0-9]{10,14}", fullmatch=True),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_CloudFront_디멘션에_Region_Global_항상_포함(self, distribution_id):
        """CloudFront 알람 디멘션에 Region=Global이 항상 포함되어야 한다."""
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "DistributionId"}
        dims = _build_dimensions(alarm_def, distribution_id, "CloudFront", {})

        region_dim = next((d for d in dims if d["Name"] == "Region"), None)
        assert region_dim is not None, f"Region 디멘션 없음: {dims}"
        assert region_dim["Value"] == "Global", (
            f"CloudFront Region 값이 Global이 아님: {region_dim['Value']}"
        )


# ──────────────────────────────────────────────
# Property 4: _extract_elb_dimension ALB/NLB vs TG 구분
# ──────────────────────────────────────────────

class TestExtractElbDimensionProperties:
    @given(
        name=safe_name,
        h=hash_part,
        acct=account_id,
        r=region,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_ALB_ARN은_app_prefix로_시작(self, name, h, acct, r):
        from common.dimension_builder import _extract_elb_dimension

        arn = f"arn:aws:elasticloadbalancing:{r}:{acct}:loadbalancer/app/{name}/{h}"
        result = _extract_elb_dimension(arn)
        assert result.startswith("app/"), f"ALB Short_ID가 app/으로 시작 안 함: {result}"

    @given(
        name=safe_name,
        h=hash_part,
        acct=account_id,
        r=region,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_NLB_ARN은_net_prefix로_시작(self, name, h, acct, r):
        from common.dimension_builder import _extract_elb_dimension

        arn = f"arn:aws:elasticloadbalancing:{r}:{acct}:loadbalancer/net/{name}/{h}"
        result = _extract_elb_dimension(arn)
        assert result.startswith("net/"), f"NLB Short_ID가 net/으로 시작 안 함: {result}"

    @given(
        name=safe_name,
        h=hash_part,
        acct=account_id,
        r=region,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_TG_ARN은_targetgroup_prefix로_시작(self, name, h, acct, r):
        from common.dimension_builder import _extract_elb_dimension

        arn = f"arn:aws:elasticloadbalancing:{r}:{acct}:targetgroup/{name}/{h}"
        result = _extract_elb_dimension(arn)
        assert result.startswith("targetgroup/"), (
            f"TG Short_ID가 targetgroup/으로 시작 안 함: {result}"
        )
