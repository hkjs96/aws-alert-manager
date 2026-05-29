"""
공통 pytest 픽스처 - Requirements 6.1

boto3 모킹, 환경 변수, 샘플 리소스 데이터 픽스처 제공
"""

import os
import sys
from unittest.mock import patch, MagicMock

# tests/ 디렉터리를 sys.path에 추가 — patch_helpers 등 로컬 헬퍼 import 지원
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from common import ResourceInfo

# 재사용 가능한 패치 헬퍼는 patch_helpers.py에 정의 — 직접 import해서 사용 가능
from patch_helpers import patch_infra_stages, patch_all_collectors  # noqa: F401


def pytest_collection_modifyitems(items):
    """Hypothesis(property-based) 테스트를 자동으로 `pbt` 마커로 분류한다.

    @given 테스트는 무겁고(경우의 수 생성) 메모리도 많이 쓴다. 파일명(test_pbt_*)
    규칙은 test_collectors/test_daily_monitor 처럼 @given을 쓰지만 이름이 다른
    파일을 놓치므로, 테스트의 *성격*으로 분류한다. 새 @given 테스트도 자동 편입된다.
    빠른 게이트는 `-m "not pbt and not e2e"`로 이 tier를 제외한다.
    """
    for item in items:
        fn = getattr(item, "obj", None)
        if getattr(fn, "is_hypothesis_test", False) or getattr(fn, "hypothesis", None) is not None:
            item.add_marker("pbt")


# ──────────────────────────────────────────────
# AWS 자격증명 픽스처
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _aws_default_region():
    """모든 테스트에 AWS_DEFAULT_REGION을 설정해 NoRegionError 방지."""
    with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}, clear=False):
        yield


@pytest.fixture(autouse=True)
def _reset_all_cw_clients():
    """모든 모듈의 캐시된 boto3 클라이언트 초기화 (CW + SNS)."""
    from common._clients import _get_cw_client
    from common.sns_notifier import _get_sns_client
    _get_cw_client.cache_clear()
    _get_sns_client.cache_clear()
    yield
    _get_cw_client.cache_clear()
    _get_sns_client.cache_clear()


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
            "Threshold_CPUUtilization": "90",
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
            "Threshold_DatabaseConnections": "200",
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
