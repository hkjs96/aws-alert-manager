"""
공통 pytest 픽스처 - Requirements 6.1

boto3 모킹, 환경 변수, 샘플 리소스 데이터 픽스처 제공
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from common import ResourceInfo


# ──────────────────────────────────────────────
# AWS 자격증명 픽스처
# ──────────────────────────────────────────────

@pytest.fixture
def aws_credentials():
    """moto 사용을 위한 가짜 AWS 자격증명 환경변수 설정"""
    with patch.dict(os.environ, {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }):
        yield


# ──────────────────────────────────────────────
# boto3 SNS 클라이언트 모킹 픽스처
# ──────────────────────────────────────────────

@pytest.fixture
def mock_sns_client():
    """boto3 SNS 클라이언트 모킹"""
    with patch("boto3.client") as mock_client:
        mock_sns = MagicMock()
        mock_client.return_value = mock_sns
        mock_sns.publish.return_value = {"MessageId": "test-message-id"}
        yield mock_sns


# ──────────────────────────────────────────────
# 환경 변수 픽스처
# ──────────────────────────────────────────────

@pytest.fixture
def default_env_vars():
    """기본 임계치 및 SNS 토픽 환경변수 설정"""
    env = {
        "DEFAULT_CPU_THRESHOLD": "80",
        "DEFAULT_MEMORY_THRESHOLD": "80",
        "DEFAULT_CONNECTIONS_THRESHOLD": "100",
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test-topic",
    }
    with patch.dict(os.environ, env):
        yield env


# ──────────────────────────────────────────────
# 샘플 리소스 픽스처
# ──────────────────────────────────────────────

@pytest.fixture
def sample_ec2_resource() -> ResourceInfo:
    """샘플 EC2 ResourceInfo 딕셔너리"""
    return ResourceInfo(
        id="i-1234567890abcdef0",
        type="EC2",
        tags={
            "Monitoring": "on",
            "Threshold_CPU": "90",
            "Name": "test-ec2-instance",
        },
        region="us-east-1",
    )


@pytest.fixture
def sample_rds_resource() -> ResourceInfo:
    """샘플 RDS ResourceInfo 딕셔너리"""
    return ResourceInfo(
        id="db-test-instance",
        type="RDS",
        tags={
            "Monitoring": "on",
            "Threshold_Connections": "200",
            "Name": "test-rds-instance",
        },
        region="us-east-1",
    )


@pytest.fixture
def sample_elb_resource() -> ResourceInfo:
    """샘플 ELB ResourceInfo 딕셔너리"""
    return ResourceInfo(
        id="test-load-balancer",
        type="ELB",
        tags={
            "Monitoring": "on",
            "Name": "test-elb",
        },
        region="us-east-1",
    )
