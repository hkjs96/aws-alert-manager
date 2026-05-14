"""
Property 5: Factory return structure

create_clients_for_account가 {"cw", "ec2", "rds", "elbv2"} 키를 가진
dict를 반환하는지 검증한다.

**Validates: Requirements 6.1, 6.2, 6.3**
"""

import json
import uuid

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from common._clients import create_clients_for_account

# Strategy: valid session names (alphanumeric + limited special chars)
session_names = st.text(
    alphabet=st.sampled_from(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    ),
    min_size=2,
    max_size=30,
)

_EXPECTED_KEYS = {"cw", "ec2", "rds", "elbv2"}

_TRUST_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
        "Action": "sts:AssumeRole",
    }],
})


class TestFactoryReturnStructure:
    """Property 5: create_clients_for_account returns dict with expected keys.

    **Validates: Requirements 6.1, 6.2, 6.3**
    """

    @mock_aws
    @given(session_name=session_names)
    @settings(max_examples=20, deadline=None)
    def test_factory_returns_expected_keys(self, session_name):
        """**Validates: Requirements 6.1, 6.2, 6.3**"""
        iam = boto3.client("iam", region_name="us-east-1")
        unique_name = f"TestRole-{uuid.uuid4().hex[:12]}"
        role_arn = iam.create_role(
            RoleName=unique_name,
            AssumeRolePolicyDocument=_TRUST_POLICY,
        )["Role"]["Arn"]

        clients = create_clients_for_account(role_arn, session_name=session_name)

        assert isinstance(clients, dict)
        assert set(clients.keys()) == _EXPECTED_KEYS
        for key in _EXPECTED_KEYS:
            assert hasattr(clients[key], "meta"), (
                f"clients['{key}'] is not a boto3 client"
            )
