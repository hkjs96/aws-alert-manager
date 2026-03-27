"""
Property 1: Bug Condition — TG 알람 단일 디멘션 버그

TG(Target Group) 리소스에 대해 _create_standard_alarm() 호출 시
put_metric_alarm에 전달되는 Dimensions를 검사하여:
  - TargetGroup 디멘션 존재 확인
  - LoadBalancer 디멘션 존재 확인 (수정 전 코드에서 FAIL 예상)
  - len(dimensions) >= 2 확인

NLB TG에 대해 namespace가 AWS/NetworkELB인지 확인
(수정 전 코드에서 FAIL 예상 — AWS/ApplicationELB 하드코딩)

**Validates: Requirements 1.1, 1.2, 1.3**
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.alarm_manager import (
    _create_standard_alarm,
    _get_alarm_defs,
)


# ──────────────────────────────────────────────
# Hypothesis 전략: TG ARN + LB ARN 조합
# ──────────────────────────────────────────────

# TG 이름: 영소문자+숫자+하이픈, 1~32자
_tg_names = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)

# TG hash suffix: 16자 hex
_tg_hashes = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# LB 이름: 영소문자+숫자+하이픈
_lb_names = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)

# LB hash suffix
_lb_hashes = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# LB 타입: application 또는 network
_lb_types = st.sampled_from(["application", "network"])

# AWS 리전
_regions = st.sampled_from(["us-east-1", "ap-northeast-2", "eu-west-1"])

# AWS 계정 ID: 12자리 숫자
_account_ids = st.from_regex(r"[0-9]{12}", fullmatch=True)


@st.composite
def tg_alarm_inputs(draw):
    """유효한 TG ARN + LB ARN 조합 생성."""
    region = draw(_regions)
    account_id = draw(_account_ids)
    tg_name = draw(_tg_names)
    tg_hash = draw(_tg_hashes)
    lb_name = draw(_lb_names)
    lb_hash = draw(_lb_hashes)
    lb_type = draw(_lb_types)

    # LB 타입에 따른 prefix
    lb_prefix = "app" if lb_type == "application" else "net"

    tg_arn = (
        f"arn:aws:elasticloadbalancing:{region}:{account_id}"
        f":targetgroup/{tg_name}/{tg_hash}"
    )
    lb_arn = (
        f"arn:aws:elasticloadbalancing:{region}:{account_id}"
        f":loadbalancer/{lb_prefix}/{lb_name}/{lb_hash}"
    )

    resource_tags = {
        "Monitoring": "on",
        "Name": tg_name,
        "_lb_arn": lb_arn,
        "_lb_type": lb_type,
    }

    return tg_arn, lb_type, resource_tags


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123456789012:alert")


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    from common._clients import _get_cw_client
    _get_cw_client.cache_clear()
    yield
    _get_cw_client.cache_clear()


# ──────────────────────────────────────────────
# Bug Condition Exploration Tests
# ──────────────────────────────────────────────

class TestTGCompoundDimension:
    """
    TG 알람 생성 시 TargetGroup + LoadBalancer 복합 디멘션이
    포함되어야 하는지 검증.

    수정 전 코드에서 FAIL 예상 — 버그 존재 증명.

    **Validates: Requirements 1.1, 1.2, 1.3**
    """

    @given(data=tg_alarm_inputs())
    @settings(max_examples=30, deadline=None)
    def test_tg_alarm_has_compound_dimensions(self, data):
        """
        **Property 1: Bug Condition** — TG 알람 복합 디멘션

        TG 리소스에 대해 _create_standard_alarm() 호출 시
        put_metric_alarm에 전달되는 Dimensions에
        TargetGroup과 LoadBalancer가 모두 포함되어야 한다.

        수정 전 코드에서 LoadBalancer 누락으로 FAIL 예상.

        **Validates: Requirements 1.1**
        """
        tg_arn, lb_type, resource_tags = data

        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.return_value = {}

        # TG 알람 정의 중 첫 번째 사용
        alarm_defs = _get_alarm_defs("TG")
        assert len(alarm_defs) > 0, "TG alarm definitions should exist"
        alarm_def = alarm_defs[0]

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_standard_alarm(
                alarm_def, tg_arn, "TG", resource_tags, mock_cw,
            )

        assert mock_cw.put_metric_alarm.called, "put_metric_alarm should be called"

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        dimensions = kwargs["Dimensions"]
        dim_names = {d["Name"] for d in dimensions}

        # TargetGroup 디멘션 존재 확인
        assert "TargetGroup" in dim_names, (
            f"TargetGroup dimension missing. "
            f"Dimensions={dimensions}"
        )

        # LoadBalancer 디멘션 존재 확인 (수정 전 FAIL 예상)
        assert "LoadBalancer" in dim_names, (
            f"LoadBalancer dimension missing from TG alarm. "
            f"TG ARN={tg_arn}, LB ARN={resource_tags['_lb_arn']}. "
            f"Dimensions={dimensions}"
        )

        # 최소 2개 디멘션
        assert len(dimensions) >= 2, (
            f"TG alarm should have >= 2 dimensions, got {len(dimensions)}. "
            f"Dimensions={dimensions}"
        )

    @given(data=tg_alarm_inputs())
    @settings(max_examples=30, deadline=None)
    def test_nlb_tg_alarm_uses_correct_namespace(self, data):
        """
        **Property 1: Bug Condition** — NLB TG namespace 동적 결정

        NLB TG 리소스에 대해 _create_standard_alarm() 호출 시
        namespace가 AWS/NetworkELB여야 한다.

        수정 전 코드에서 AWS/ApplicationELB 하드코딩으로 FAIL 예상.

        **Validates: Requirements 1.1, 1.3**
        """
        tg_arn, lb_type, resource_tags = data

        # NLB TG만 테스트
        assume(lb_type == "network")

        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.return_value = {}

        alarm_defs = _get_alarm_defs("TG")
        alarm_def = alarm_defs[0]

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_standard_alarm(
                alarm_def, tg_arn, "TG", resource_tags, mock_cw,
            )

        assert mock_cw.put_metric_alarm.called, "put_metric_alarm should be called"

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        namespace = kwargs["Namespace"]

        assert namespace == "AWS/NetworkELB", (
            f"NLB TG alarm should use AWS/NetworkELB namespace, "
            f"but got '{namespace}'. "
            f"lb_type={lb_type}, TG ARN={tg_arn}"
        )


# ──────────────────────────────────────────────
# Hypothesis 전략: 비TG 리소스 (ALB, NLB, EC2, RDS)
# ──────────────────────────────────────────────

# EC2 인스턴스 ID: i- + 17자 hex
_ec2_ids = st.from_regex(r"i-[0-9a-f]{17}", fullmatch=True)

# RDS DB 인스턴스 ID: 영소문자+숫자+하이픈, 1~63자
_rds_ids = st.from_regex(r"[a-z][a-z0-9\-]{0,30}[a-z0-9]", fullmatch=True)

# ALB ARN 생성
@st.composite
def alb_inputs(draw):
    """유효한 ALB ARN + 알람 정의 조합 생성."""
    region = draw(_regions)
    account_id = draw(_account_ids)
    lb_name = draw(_lb_names)
    lb_hash = draw(_lb_hashes)

    alb_arn = (
        f"arn:aws:elasticloadbalancing:{region}:{account_id}"
        f":loadbalancer/app/{lb_name}/{lb_hash}"
    )
    resource_tags = {"Monitoring": "on", "Name": lb_name}
    return alb_arn, "ALB", resource_tags


# NLB ARN 생성
@st.composite
def nlb_inputs(draw):
    """유효한 NLB ARN + 알람 정의 조합 생성."""
    region = draw(_regions)
    account_id = draw(_account_ids)
    lb_name = draw(_lb_names)
    lb_hash = draw(_lb_hashes)

    nlb_arn = (
        f"arn:aws:elasticloadbalancing:{region}:{account_id}"
        f":loadbalancer/net/{lb_name}/{lb_hash}"
    )
    resource_tags = {"Monitoring": "on", "Name": lb_name}
    return nlb_arn, "NLB", resource_tags


# EC2 입력 생성
@st.composite
def ec2_inputs(draw):
    """유효한 EC2 인스턴스 ID + 알람 정의 조합 생성."""
    instance_id = draw(_ec2_ids)
    resource_tags = {"Monitoring": "on", "Name": f"srv-{instance_id[-8:]}"}
    return instance_id, "EC2", resource_tags


# RDS 입력 생성
@st.composite
def rds_inputs(draw):
    """유효한 RDS DB 인스턴스 ID + 알람 정의 조합 생성."""
    db_id = draw(_rds_ids)
    resource_tags = {"Monitoring": "on", "Name": db_id}
    return db_id, "RDS", resource_tags


# 모든 비TG 리소스 입력을 하나의 전략으로 통합
non_tg_inputs = st.one_of(alb_inputs(), nlb_inputs(), ec2_inputs(), rds_inputs())


# 기대 디멘션/네임스페이스 매핑 (수정 전 코드의 관찰 결과)
_EXPECTED_DIM_KEY = {
    "ALB": "LoadBalancer",
    "NLB": "LoadBalancer",
    "EC2": "InstanceId",
    "RDS": "DBInstanceIdentifier",
}

_EXPECTED_NAMESPACE = {
    "ALB": "AWS/ApplicationELB",
    "NLB": "AWS/NetworkELB",
}


def _expected_dim_value(resource_id: str, resource_type: str) -> str:
    """수정 전 코드의 디멘션 값 계산 로직 재현."""
    if resource_type in ("ALB", "NLB"):
        return _extract_elb_dimension(resource_id)
    return resource_id


from common.alarm_manager import _extract_elb_dimension


# ──────────────────────────────────────────────
# Preservation Property Tests
# ──────────────────────────────────────────────

class TestPreservationNonTGDimensions:
    """
    Property 2: Preservation — 비TG 리소스 디멘션 불변

    수정 전 코드에서 비TG 리소스(ALB, NLB, EC2, RDS)의
    _create_standard_alarm() 호출 시 디멘션이 기존 로직과 동일한지 검증.

    관찰 기준선:
    - ALB: LoadBalancer 단일 디멘션, namespace AWS/ApplicationELB
    - NLB: LoadBalancer 단일 디멘션, namespace AWS/NetworkELB
    - EC2: InstanceId 단일 디멘션
    - RDS: DBInstanceIdentifier 단일 디멘션

    수정 전 코드에서 PASS 예상 (기존 동작 기준선 확인).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(data=non_tg_inputs)
    @settings(max_examples=50, deadline=None)
    def test_non_tg_single_dimension_preserved(self, data):
        """
        **Property 2: Preservation** — 비TG 리소스 단일 디멘션 불변

        resource_type ∈ {ALB, NLB, EC2, RDS} × 랜덤 resource_id에 대해
        _create_standard_alarm() 호출 시 디멘션이 기존 로직과 동일한지 검증.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        resource_id, resource_type, resource_tags = data

        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.return_value = {}

        alarm_defs = _get_alarm_defs(resource_type)
        assert len(alarm_defs) > 0, f"{resource_type} alarm definitions should exist"

        # 각 리소스 타입의 첫 번째 알람 정의로 테스트 (Disk 제외)
        alarm_def = next(
            (d for d in alarm_defs if not d.get("dynamic_dimensions")),
            alarm_defs[0],
        )

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_standard_alarm(
                alarm_def, resource_id, resource_type, resource_tags, mock_cw,
            )

        assert mock_cw.put_metric_alarm.called, "put_metric_alarm should be called"

        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        dimensions = kwargs["Dimensions"]

        # 기대 디멘션 키
        expected_key = _EXPECTED_DIM_KEY[resource_type]
        expected_value = _expected_dim_value(resource_id, resource_type)

        # 단일 디멘션 확인 (extra_dimensions가 없는 경우)
        if not alarm_def.get("extra_dimensions"):
            assert len(dimensions) == 1, (
                f"{resource_type} should have exactly 1 dimension, "
                f"got {len(dimensions)}: {dimensions}"
            )

        # 첫 번째 디멘션이 기대값과 일치
        assert dimensions[0]["Name"] == expected_key, (
            f"{resource_type} dimension key should be '{expected_key}', "
            f"got '{dimensions[0]['Name']}'"
        )
        assert dimensions[0]["Value"] == expected_value, (
            f"{resource_type} dimension value should be '{expected_value}', "
            f"got '{dimensions[0]['Value']}'"
        )

    @given(data=st.one_of(alb_inputs(), nlb_inputs()))
    @settings(max_examples=30, deadline=None)
    def test_alb_nlb_namespace_preserved(self, data):
        """
        **Property 2: Preservation** — ALB/NLB namespace 불변

        ALB → AWS/ApplicationELB, NLB → AWS/NetworkELB namespace가
        기존 로직과 동일한지 검증.

        **Validates: Requirements 3.1, 3.2**
        """
        resource_id, resource_type, resource_tags = data

        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.return_value = {}

        alarm_defs = _get_alarm_defs(resource_type)
        alarm_def = alarm_defs[0]

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            _create_standard_alarm(
                alarm_def, resource_id, resource_type, resource_tags, mock_cw,
            )

        assert mock_cw.put_metric_alarm.called
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs

        expected_ns = _EXPECTED_NAMESPACE[resource_type]
        assert kwargs["Namespace"] == expected_ns, (
            f"{resource_type} namespace should be '{expected_ns}', "
            f"got '{kwargs['Namespace']}'"
        )
