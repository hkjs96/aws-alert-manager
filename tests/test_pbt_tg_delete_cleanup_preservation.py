# Feature: tg-delete-alarm-cleanup, Property 2: Preservation - 기존 DELETE/MODIFY/TAG_CHANGE 이벤트 파싱 보존
"""
Preservation Test - 기존 이벤트 파싱 동작 보존

Property 2 (Preservation): DeleteTargetGroup 버그 수정 전후로 기존 지원 이벤트
(TerminateInstances, DeleteDBInstance, DeleteLoadBalancer, ModifyInstanceAttribute 등)의
parse_cloudtrail_event() 결과가 동일해야 한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

EXPECTED: This test PASSES on unfixed code (baseline for existing behavior).
After the fix, this test should CONTINUE TO PASS (no regression).
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from remediation_handler.lambda_handler import parse_cloudtrail_event

# ── Hypothesis 전략: 공통 빌딩 블록 ──

aws_regions = st.sampled_from([
    "us-east-1", "us-west-2", "eu-west-1", "ap-northeast-2",
    "ap-southeast-1", "eu-central-1",
])

aws_account_ids = st.from_regex(r"[0-9]{12}", fullmatch=True)

# EC2 인스턴스 ID
ec2_instance_ids = st.from_regex(r"i-[a-f0-9]{17}", fullmatch=True)

# RDS DB identifier
rds_db_ids = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)

# ALB ARN
alb_names = st.from_regex(r"[a-z][a-z0-9\-]{0,31}", fullmatch=True)
alb_hashes = st.from_regex(r"[a-f0-9]{16}", fullmatch=True)
alb_arns = st.builds(
    lambda region, account, name, h:
        f"arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/app/{name}/{h}",
    region=aws_regions, account=aws_account_ids, name=alb_names, h=alb_hashes,
)

# NLB ARN
nlb_names = st.from_regex(r"[a-z][a-z0-9\-]{0,31}", fullmatch=True)
nlb_hashes = st.from_regex(r"[a-f0-9]{16}", fullmatch=True)
nlb_arns = st.builds(
    lambda region, account, name, h:
        f"arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/net/{name}/{h}",
    region=aws_regions, account=aws_account_ids, name=nlb_names, h=nlb_hashes,
)

# TG ARN (for AddTags/RemoveTags on TG resources)
tg_names = st.from_regex(r"[a-z][a-z0-9\-]{0,31}", fullmatch=True)
tg_hashes = st.from_regex(r"[a-f0-9]{16}", fullmatch=True)
tg_arns = st.builds(
    lambda region, account, name, h:
        f"arn:aws:elasticloadbalancing:{region}:{account}:targetgroup/{name}/{h}",
    region=aws_regions, account=aws_account_ids, name=tg_names, h=tg_hashes,
)

# ELB ARN (ALB or NLB) for ELB-type events
elb_arns = st.one_of(alb_arns, nlb_arns)

# ELB tag resource ARN (ALB, NLB, or TG) for AddTags/RemoveTags
elb_tag_arns = st.one_of(alb_arns, nlb_arns, tg_arns)

# RDS ARN for AddTagsToResource/RemoveTagsFromResource
rds_tag_arns = st.builds(
    lambda region, account, db_id:
        f"arn:aws:rds:{region}:{account}:db:{db_id}",
    region=aws_regions, account=aws_account_ids, db_id=rds_db_ids,
)


# ── 이벤트 생성 헬퍼 ──

def _make_event(event_name: str, request_params: dict) -> dict:
    """EventBridge 래핑 CloudTrail 이벤트 생성."""
    return {
        "detail": {
            "eventName": event_name,
            "requestParameters": request_params,
        },
    }


# ── 이벤트별 기대 매핑 ──
# _API_MAP의 resource_type이 "ELB"인 경우 _resolve_elb_type()에 의해
# ALB/NLB/TG로 세분화됨. 여기서는 ARN 기반으로 기대값을 결정.

def _expected_resource_type_for_elb_arn(arn: str) -> str:
    """ELB ARN에서 기대 resource_type 결정 (현재 _resolve_elb_type 동작과 동일)."""
    if "/app/" in arn:
        return "ALB"
    if "/net/" in arn:
        return "NLB"
    # targetgroup/ ARN은 현재 "ELB"로 폴백됨
    return "ELB"


class TestExistingEventPreservation:
    """
    Preservation Property: 기존 _API_MAP에 등록된 모든 이벤트에 대해
    parse_cloudtrail_event()가 올바른 resource_type과 event_category를 반환한다.

    이 테스트는 수정 전 코드에서 PASS하여 기존 동작의 기준선을 확립하고,
    수정 후에도 PASS하여 회귀가 없음을 검증한다.
    """

    # ── EC2 DELETE: TerminateInstances ──

    @given(instance_id=ec2_instance_ids)
    @settings(max_examples=30)
    def test_terminate_instances(self, instance_id: str):
        """
        **Validates: Requirements 3.2**

        TerminateInstances → resource_type="EC2", event_category="DELETE"
        """
        event = _make_event("TerminateInstances", {
            "instancesSet": {"items": [{"instanceId": instance_id}]},
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "DELETE"
        assert parsed.resource_id == instance_id

    # ── RDS DELETE: DeleteDBInstance ──

    @given(db_id=rds_db_ids)
    @settings(max_examples=30)
    def test_delete_db_instance(self, db_id: str):
        """
        **Validates: Requirements 3.3**

        DeleteDBInstance → resource_type="RDS", event_category="DELETE"
        """
        event = _make_event("DeleteDBInstance", {
            "dBInstanceIdentifier": db_id,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "DELETE"
        assert parsed.resource_id == db_id

    # ── ALB DELETE: DeleteLoadBalancer with ALB ARN ──

    @given(arn=alb_arns)
    @settings(max_examples=30)
    def test_delete_load_balancer_alb(self, arn: str):
        """
        **Validates: Requirements 3.1**

        DeleteLoadBalancer with ALB ARN → resource_type="ALB", event_category="DELETE"
        """
        event = _make_event("DeleteLoadBalancer", {
            "loadBalancerArn": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "DELETE"
        assert parsed.resource_id == arn

    # ── NLB DELETE: DeleteLoadBalancer with NLB ARN ──

    @given(arn=nlb_arns)
    @settings(max_examples=30)
    def test_delete_load_balancer_nlb(self, arn: str):
        """
        **Validates: Requirements 3.1**

        DeleteLoadBalancer with NLB ARN → resource_type="NLB", event_category="DELETE"
        """
        event = _make_event("DeleteLoadBalancer", {
            "loadBalancerArn": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "NLB"
        assert parsed.event_category == "DELETE"
        assert parsed.resource_id == arn

    # ── EC2 MODIFY: ModifyInstanceAttribute ──

    @given(instance_id=ec2_instance_ids)
    @settings(max_examples=30)
    def test_modify_instance_attribute(self, instance_id: str):
        """
        **Validates: Requirements 3.4**

        ModifyInstanceAttribute → resource_type="EC2", event_category="MODIFY"
        """
        event = _make_event("ModifyInstanceAttribute", {
            "instanceId": instance_id,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == instance_id

    # ── EC2 MODIFY: ModifyInstanceType ──

    @given(instance_id=ec2_instance_ids)
    @settings(max_examples=30)
    def test_modify_instance_type(self, instance_id: str):
        """
        **Validates: Requirements 3.4**

        ModifyInstanceType → resource_type="EC2", event_category="MODIFY"
        """
        event = _make_event("ModifyInstanceType", {
            "instanceId": instance_id,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == instance_id

    # ── RDS MODIFY: ModifyDBInstance ──

    @given(db_id=rds_db_ids)
    @settings(max_examples=30)
    def test_modify_db_instance(self, db_id: str):
        """
        **Validates: Requirements 3.4**

        ModifyDBInstance → resource_type="RDS", event_category="MODIFY"
        """
        event = _make_event("ModifyDBInstance", {
            "dBInstanceIdentifier": db_id,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == db_id

    # ── ELB MODIFY: ModifyLoadBalancerAttributes (ALB) ──

    @given(arn=alb_arns)
    @settings(max_examples=30)
    def test_modify_load_balancer_attributes_alb(self, arn: str):
        """
        **Validates: Requirements 3.4**

        ModifyLoadBalancerAttributes with ALB ARN → resource_type="ALB", event_category="MODIFY"
        """
        event = _make_event("ModifyLoadBalancerAttributes", {
            "loadBalancerArn": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == arn

    # ── ELB MODIFY: ModifyLoadBalancerAttributes (NLB) ──

    @given(arn=nlb_arns)
    @settings(max_examples=30)
    def test_modify_load_balancer_attributes_nlb(self, arn: str):
        """
        **Validates: Requirements 3.4**

        ModifyLoadBalancerAttributes with NLB ARN → resource_type="NLB", event_category="MODIFY"
        """
        event = _make_event("ModifyLoadBalancerAttributes", {
            "loadBalancerArn": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "NLB"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == arn

    # ── ELB MODIFY: ModifyListener (ALB) ──

    @given(arn=alb_arns)
    @settings(max_examples=30)
    def test_modify_listener_alb(self, arn: str):
        """
        **Validates: Requirements 3.4**

        ModifyListener with ALB ARN → resource_type="ALB", event_category="MODIFY"
        """
        event = _make_event("ModifyListener", {
            "loadBalancerArn": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "MODIFY"
        assert parsed.resource_id == arn

    # ── EC2 TAG_CHANGE: CreateTags ──

    @given(instance_id=ec2_instance_ids)
    @settings(max_examples=30)
    def test_create_tags(self, instance_id: str):
        """
        **Validates: Requirements 3.5**

        CreateTags → resource_type="EC2", event_category="TAG_CHANGE"
        """
        event = _make_event("CreateTags", {
            "resourcesSet": {"items": [{"resourceId": instance_id}]},
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == instance_id

    # ── EC2 TAG_CHANGE: DeleteTags ──

    @given(instance_id=ec2_instance_ids)
    @settings(max_examples=30)
    def test_delete_tags(self, instance_id: str):
        """
        **Validates: Requirements 3.5**

        DeleteTags → resource_type="EC2", event_category="TAG_CHANGE"
        """
        event = _make_event("DeleteTags", {
            "resourcesSet": {"items": [{"resourceId": instance_id}]},
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "EC2"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == instance_id

    # ── RDS TAG_CHANGE: AddTagsToResource ──

    @given(arn=rds_tag_arns)
    @settings(max_examples=30)
    def test_add_tags_to_resource_rds(self, arn: str):
        """
        **Validates: Requirements 3.5**

        AddTagsToResource → resource_type="RDS", event_category="TAG_CHANGE"
        """
        event = _make_event("AddTagsToResource", {
            "resourceName": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"
        # RDS tag extractor splits on ":db:" to get the DB identifier
        expected_id = arn.split(":db:")[-1]
        assert parsed.resource_id == expected_id

    # ── RDS TAG_CHANGE: RemoveTagsFromResource ──

    @given(arn=rds_tag_arns)
    @settings(max_examples=30)
    def test_remove_tags_from_resource_rds(self, arn: str):
        """
        **Validates: Requirements 3.5**

        RemoveTagsFromResource → resource_type="RDS", event_category="TAG_CHANGE"
        """
        event = _make_event("RemoveTagsFromResource", {
            "resourceName": arn,
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "RDS"
        assert parsed.event_category == "TAG_CHANGE"
        expected_id = arn.split(":db:")[-1]
        assert parsed.resource_id == expected_id

    # ── ELB TAG_CHANGE: AddTags (ALB) ──

    @given(arn=alb_arns)
    @settings(max_examples=30)
    def test_add_tags_elb_alb(self, arn: str):
        """
        **Validates: Requirements 3.5**

        AddTags with ALB ARN → resource_type="ALB", event_category="TAG_CHANGE"
        """
        event = _make_event("AddTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn

    # ── ELB TAG_CHANGE: AddTags (NLB) ──

    @given(arn=nlb_arns)
    @settings(max_examples=30)
    def test_add_tags_elb_nlb(self, arn: str):
        """
        **Validates: Requirements 3.5**

        AddTags with NLB ARN → resource_type="NLB", event_category="TAG_CHANGE"
        """
        event = _make_event("AddTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "NLB"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn

    # ── ELB TAG_CHANGE: AddTags (TG ARN → "ELB" fallback) ──
    # NOTE: 현재 _resolve_elb_type()는 targetgroup/ ARN을 "ELB"로 폴백.
    # elb-resource-type-split 완료 후에도 이 동작이 유지되는지 확인.

    @given(arn=tg_arns)
    @settings(max_examples=30)
    def test_add_tags_elb_tg(self, arn: str):
        """
        **Validates: Requirements 3.5**

        AddTags with TG ARN → _resolve_elb_type fallback, event_category="TAG_CHANGE"
        """
        event = _make_event("AddTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == _expected_resource_type_for_elb_arn(arn)
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn

    # ── ELB TAG_CHANGE: RemoveTags (ALB) ──

    @given(arn=alb_arns)
    @settings(max_examples=30)
    def test_remove_tags_elb_alb(self, arn: str):
        """
        **Validates: Requirements 3.5**

        RemoveTags with ALB ARN → resource_type="ALB", event_category="TAG_CHANGE"
        """
        event = _make_event("RemoveTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "ALB"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn

    # ── ELB TAG_CHANGE: RemoveTags (NLB) ──

    @given(arn=nlb_arns)
    @settings(max_examples=30)
    def test_remove_tags_elb_nlb(self, arn: str):
        """
        **Validates: Requirements 3.5**

        RemoveTags with NLB ARN → resource_type="NLB", event_category="TAG_CHANGE"
        """
        event = _make_event("RemoveTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == "NLB"
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn

    # ── ELB TAG_CHANGE: RemoveTags (TG ARN → "ELB" fallback) ──

    @given(arn=tg_arns)
    @settings(max_examples=30)
    def test_remove_tags_elb_tg(self, arn: str):
        """
        **Validates: Requirements 3.5**

        RemoveTags with TG ARN → _resolve_elb_type fallback, event_category="TAG_CHANGE"
        """
        event = _make_event("RemoveTags", {
            "resourceArns": [arn],
        })
        parsed = parse_cloudtrail_event(event)
        assert parsed.resource_type == _expected_resource_type_for_elb_arn(arn)
        assert parsed.event_category == "TAG_CHANGE"
        assert parsed.resource_id == arn
