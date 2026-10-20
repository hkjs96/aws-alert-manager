"""
공통 pytest 픽스처 - Requirements 6.1

boto3 모킹, 환경 변수, 샘플 리소스 데이터 픽스처 제공
"""

import os
import sys
from unittest.mock import patch, MagicMock

# tests/ 디렉터리를 sys.path에 추가 — patch_helpers 등 로컬 헬퍼 import 지원
sys.path.insert(0, os.path.dirname(__file__))

# 테스트는 실제 AWS에 닿지 않는다 — boto3가 세션을 만들기 전에(import 시점) 개발자 PC의 프로필·자격증명을 지우고
# 가짜 자격증명을 준다. 2026-10-14: 목이 빠진 호출이 개발자의 (만료된) SSO 프로필로 실제 엔드포인트에 나가 재시도·토큰
# 갱신을 기다렸다 — 한 테스트가 968초, 빠른 게이트 전체가 33분. 순서에 따라 자격증명 없음 500이 나던 테스트도 같은 원인.
for _var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SSO_SESSION"):
    os.environ.pop(_var, None)
os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_EC2_METADATA_DISABLED": "true",
    # ~/.aws/config의 SSO 프로필을 읽지 않게 존재하지 않는 경로로
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
})

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
def _region_probes_offline(request):
    """리전 탐지의 리전별 호출을 막는다 — 탐지 자체를 검증하는 test_region_discovery.py만 예외(거기선 목 세션을 쓴다).

    2026-10-14: 연결 테스트 API를 부르는 테스트가 34리전에 실제 TLS 연결을 열었고, 15초 기한 뒤 버려진 스레드가
    계속 돌며 CPU를 잡아 뒤 테스트 전체가 느려졌다(빠른 게이트 33분, 한 테스트 968초).
    """
    if request.node.fspath.basename == "test_region_discovery.py":
        yield
        return
    with patch("common.region_discovery._has_resources", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _live_alarms_offline():
    """대시보드·알람 목록의 CloudWatch 실시간 조회를 막는다(계정×리전마다 AssumeRole) — 기본은 알람 없음.
    조회 자체를 검증하는 테스트는 `_alarms_in`을 직접 패치한다. 캐시는 테스트마다 비운다."""
    from api_handler import cw_helper
    cw_helper._LIVE_CACHE.clear()
    with patch("api_handler.cw_helper._alarms_in", return_value=[]):
        yield
    cw_helper._LIVE_CACHE.clear()


@pytest.fixture(autouse=True)
def _tag_cache_off():
    """단위 테스트에서 RGT 프라임(실제 boto3 호출)을 막고 활성 태그 캐시를 격리한다.

    캐시 자체를 검증하는 tests/test_tag_cache.py는 이 env를 다시 지운다.
    """
    from common.tag_cache import set_active_tag_cache

    set_active_tag_cache(None)
    with patch.dict(os.environ, {"TAG_CACHE": "off"}, clear=False):
        yield
    set_active_tag_cache(None)


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


@pytest.fixture(autouse=True)
def _worker_single_region(request):
    """정기 워커 테스트는 예전 범위(us-east-1 한 리전)로 고정한다 — 리전 순회 자체는 test_worker_regions.py가 본다.
    없으면 계정 표가 없는 테스트가 폴백 리전(ap-northeast-2)+us-east-1 두 번을 돌아 집계가 두 배가 된다."""
    name = request.node.fspath.basename
    if not (name.startswith("test_daily_monitor") or name == "test_worker_multiacccount.py"):
        yield
        return
    with patch("daily_monitor.lambda_handler._worker_regions", return_value=["us-east-1"]), \
         patch("daily_monitor.lambda_handler._notify_unregistered_regions", return_value=[]):
        yield
