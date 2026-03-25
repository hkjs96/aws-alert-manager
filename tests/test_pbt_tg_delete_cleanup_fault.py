# Feature: tg-delete-alarm-cleanup, Property 1: Bug Condition - DeleteTargetGroup 이벤트 파싱 실패
"""
Bug Condition Exploration Test - DeleteTargetGroup 이벤트 파싱 실패

Property 1 (Bug Condition): DeleteTargetGroup CloudTrail 이벤트가 발생하면
parse_cloudtrail_event()가 _API_MAP에 매핑이 없어
ValueError("Unsupported eventName")를 발생시키는 버그.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**

EXPECTED: This test FAILS on unfixed code because DeleteTargetGroup
is not in _API_MAP, causing ValueError("Unsupported eventName").
After the fix, this test should PASS.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from remediation_handler.lambda_handler import parse_cloudtrail_event

# ── Hypothesis 전략: 랜덤 TG ARN 생성 ──

aws_regions = st.sampled_from([
    "us-east-1", "us-west-2", "eu-west-1", "ap-northeast-2",
    "ap-southeast-1", "eu-central-1",
])

aws_account_ids = st.from_regex(r"[0-9]{12}", fullmatch=True)

tg_names = st.from_regex(r"[a-z][a-z0-9\-]{0,31}", fullmatch=True)

tg_hashes = st.from_regex(r"[a-f0-9]{16}", fullmatch=True)

tg_arns = st.builds(
    lambda region, account, name, h:
        f"arn:aws:elasticloadbalancing:{region}:{account}:targetgroup/{name}/{h}",
    region=aws_regions,
    account=aws_account_ids,
    name=tg_names,
    h=tg_hashes,
)


def _make_delete_tg_event(tg_arn: str) -> dict:
    """DeleteTargetGroup CloudTrail 이벤트 (EventBridge 래핑) 생성."""
    return {
        "detail": {
            "eventName": "DeleteTargetGroup",
            "requestParameters": {
                "targetGroupArn": tg_arn,
            },
        },
    }


class TestDeleteTargetGroupBugCondition:
    """
    Bug Condition: DeleteTargetGroup 이벤트를 parse_cloudtrail_event()에
    전달하면 _API_MAP에 매핑이 없어 ValueError가 발생한다.

    수정 후에는 resource_type="TG", event_category="DELETE",
    resource_id=targetGroupArn으로 정상 파싱되어야 한다.
    """

    @given(tg_arn=tg_arns)
    @settings(max_examples=50)
    def test_parse_delete_target_group_event(self, tg_arn: str):
        """
        **Validates: Requirements 2.1, 2.2, 2.3**

        For any valid TG ARN, a DeleteTargetGroup CloudTrail event
        should be parsed with resource_type="TG", event_category="DELETE",
        and resource_id equal to the targetGroupArn.
        """
        event = _make_delete_tg_event(tg_arn)
        parsed = parse_cloudtrail_event(event)

        assert parsed[0].resource_type == "TG", (
            f"Expected resource_type='TG', got '{parsed.resource_type}'"
        )
        assert parsed[0].event_category == "DELETE", (
            f"Expected event_category='DELETE', got '{parsed.event_category}'"
        )
        assert parsed[0].resource_id == tg_arn, (
            f"Expected resource_id='{tg_arn}', got '{parsed.resource_id}'"
        )
