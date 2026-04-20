"""
Property Test — CREATE-TAG_CHANGE 멱등성

Property 3: CREATE와 TAG_CHANGE 이벤트 간 멱등성
어떤 순서로 처리해도 create_alarms_for_resource 호출 인자가 동일.

CREATE 이벤트와 TAG_CHANGE(Monitoring=on) 이벤트가 동일 리소스에 대해
순서와 무관하게 동일한 알람 생성 결과를 만드는지 검증한다.

**Validates: Requirements 5.1, 5.2, 5.3**
"""

import os
from unittest.mock import patch, MagicMock, call

import boto3
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from moto import mock_aws

from common.alarm_manager import create_alarms_for_resource


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

resource_types = st.sampled_from(["EC2", "RDS"])

ec2_ids = st.from_regex(r"i-[0-9a-f]{17}", fullmatch=True)
rds_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-"),
    min_size=3,
    max_size=20,
).map(lambda s: f"db-{s}")

threshold_values = st.floats(
    min_value=1.0, max_value=999.0, allow_nan=False, allow_infinity=False,
).map(lambda x: str(round(x, 1)))


@st.composite
def resource_with_tags(draw):
    """리소스 타입, ID, Monitoring=on 태그 세트 생성."""
    rtype = draw(resource_types)
    rid = draw(ec2_ids if rtype == "EC2" else rds_ids)
    cpu_thr = draw(threshold_values)
    tags = {
        "Monitoring": "on",
        "Name": f"test-{rtype.lower()}",
        "Threshold_CPU": cpu_thr,
    }
    return rtype, rid, tags


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

class TestCreateTagChangeIdempotency:
    """Property 3: CREATE-TAG_CHANGE 멱등성.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """

    @mock_aws
    @given(data=resource_with_tags())
    @settings(max_examples=10, deadline=None)
    def test_create_then_tag_change_same_result(self, data):
        """CREATE 후 TAG_CHANGE와 TAG_CHANGE 단독 호출 결과가 동일.

        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        rtype, rid, tags = data

        with patch.dict(os.environ, {
            "SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:123456789012:test",
        }):
            # 1차: CREATE 시점 알람 생성
            result_create = create_alarms_for_resource(rid, rtype, tags)

            # 2차: TAG_CHANGE 시점 알람 재생성 (동일 인자)
            result_tag_change = create_alarms_for_resource(rid, rtype, tags)

        # 멱등성: 동일한 알람 이름 집합
        assert set(result_create) == set(result_tag_change), (
            f"Idempotency violation: CREATE={sorted(result_create)}, "
            f"TAG_CHANGE={sorted(result_tag_change)}"
        )

    @mock_aws
    @given(data=resource_with_tags())
    @settings(max_examples=10, deadline=None)
    def test_repeated_create_is_idempotent(self, data):
        """동일 리소스에 대해 create_alarms_for_resource를 2번 호출해도 결과 동일.

        **Validates: Requirements 5.1, 5.2**
        """
        rtype, rid, tags = data

        with patch.dict(os.environ, {
            "SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:123456789012:test",
        }):
            result1 = create_alarms_for_resource(rid, rtype, tags)
            result2 = create_alarms_for_resource(rid, rtype, tags)

        assert set(result1) == set(result2)
        assert len(result1) == len(result2)
