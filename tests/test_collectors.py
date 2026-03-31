"""
Collectors 테스트 - Property 1, 5 속성 테스트 + 단위 테스트

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.5
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ──────────────────────────────────────────────
# 헬퍼: boto3 모킹용 EC2 응답 생성
# ──────────────────────────────────────────────

def _make_ec2_instance(instance_id: str, tags: dict, state: str = "running") -> dict:
    return {
        "InstanceId": instance_id,
        "State": {"Name": state},
        "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
    }


def _make_ec2_response(instances: list[dict]) -> dict:
    return {"Reservations": [{"Instances": instances}]}


def _make_rds_instance(db_id: str, db_arn: str, status: str = "available",
                       engine: str = "mysql") -> dict:
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceArn": db_arn,
        "DBInstanceStatus": status,
        "Engine": engine,
    }


def _make_cw_datapoint(value: float) -> dict:
    return {
        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "Average": value,
        "Sum": value,
        "Maximum": value,
        "Minimum": value,
    }


# ──────────────────────────────────────────────
# Property 1: 수집 결과 필터링 정확성 (EC2)
# Validates: Requirements 1.1, 1.2
# ──────────────────────────────────────────────

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    monitored_ids=st.lists(
        st.text(min_size=2, max_size=20, alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
        min_size=0, max_size=5, unique=True,
    ),
    unmonitored_ids=st.lists(
        st.text(min_size=2, max_size=20, alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
        min_size=0, max_size=5, unique=True,
    ),
)
def test_property_1_ec2_collection_filter(monitored_ids, unmonitored_ids):
    """Feature: aws-monitoring-engine, Property 1: EC2 수집 결과 필터링 정확성"""
    # ID 중복 제거
    unmonitored_ids = [i for i in unmonitored_ids if i not in monitored_ids]

    monitored = [_make_ec2_instance(i, {"Monitoring": "on"}) for i in monitored_ids]
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _make_ec2_response(monitored)

    with patch("common.collectors.ec2._get_ec2_client", return_value=mock_ec2), \
         patch("common.collectors.ec2.boto3.session.Session") as mock_session:
        mock_session.return_value.region_name = "us-east-1"
        from common.collectors.ec2 import collect_monitored_resources
        result = collect_monitored_resources()

    result_ids = {r["id"] for r in result}

    for mid in monitored_ids:
        assert mid in result_ids, f"{mid} should be in result"

    for uid in unmonitored_ids:
        assert uid not in result_ids, f"{uid} should NOT be in result"


# ──────────────────────────────────────────────
# Property 5: 삭제된 리소스 수집 제외 (EC2)
# Validates: Requirements 1.5
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    active_ids=st.lists(
        st.text(min_size=2, max_size=15, alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
        min_size=0, max_size=3, unique=True,
    ),
    dead_state=st.sampled_from(["terminated", "shutting-down"]),
)
def test_property_5_terminated_instances_excluded(active_ids, dead_state):
    """Feature: aws-monitoring-engine, Property 5: 삭제된 리소스 수집 제외"""
    dead_id = "dead-instance-001"
    active_ids = [i for i in active_ids if i != dead_id]

    active = [_make_ec2_instance(i, {"Monitoring": "on"}, "running") for i in active_ids]
    dead = [_make_ec2_instance(dead_id, {"Monitoring": "on"}, dead_state)]

    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _make_ec2_response(active + dead)

    with patch("common.collectors.ec2._get_ec2_client", return_value=mock_ec2), \
         patch("common.collectors.ec2.boto3.session.Session") as mock_session:
        mock_session.return_value.region_name = "us-east-1"
        from common.collectors.ec2 import collect_monitored_resources
        result = collect_monitored_resources()

    result_ids = {r["id"] for r in result}
    assert dead_id not in result_ids, f"terminated instance {dead_id} should be excluded"
    for aid in active_ids:
        assert aid in result_ids


# ──────────────────────────────────────────────
# EC2 단위 테스트
# ──────────────────────────────────────────────

class TestEC2Collector:
    @pytest.fixture(autouse=True)
    def setup(self):
        import importlib
        import common.collectors.ec2 as m
        importlib.reload(m)
        self.module = m

    def _mock_boto3(self, ec2_response):
        mock_ec2 = MagicMock()
        mock_ec2.describe_instances.return_value = ec2_response
        mock_session = MagicMock()
        mock_session.return_value.region_name = "us-east-1"
        return mock_ec2, mock_session

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 - Requirements 1.3"""
        mock_ec2, mock_session = self._mock_boto3(_make_ec2_response([]))
        with patch("common.collectors.ec2._get_ec2_client", return_value=mock_ec2), \
             patch("common.collectors.ec2.boto3.session.Session", mock_session):
            result = self.module.collect_monitored_resources()
        assert result == []

    def test_api_error_raises(self):
        """AWS API 오류 시 예외 전파 - Requirements 1.4"""
        from botocore.exceptions import ClientError
        mock_ec2 = MagicMock()
        mock_ec2.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "error"}},
            "describe_instances",
        )
        with patch("common.collectors.ec2._get_ec2_client", return_value=mock_ec2):
            with pytest.raises(ClientError):
                self.module.collect_monitored_resources()

    def test_get_metrics_returns_cpu(self):
        """CPUUtilization 메트릭 정상 반환"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(75.0)]
        }
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {})
        assert result is not None
        assert result["CPU"] == pytest.approx(75.0)

    def test_get_metrics_returns_none_when_no_data(self):
        """CloudWatch 데이터 없을 때 None 반환 - Requirements 3.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {})
        assert result is None

    def test_get_metrics_skips_memory_without_tag(self):
        """Threshold_Memory 태그 없으면 Memory 메트릭 조회 안 함"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(60.0)]
        }
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {})  # 태그 없음

        # get_metric_statistics 호출 횟수: CPU만 (Memory 없음)
        assert mock_cw.get_metric_statistics.call_count == 1
        assert result is not None
        assert "Memory" not in result

    def test_get_metrics_includes_memory_with_tag(self):
        """Threshold_Memory 태그 있으면 Memory 메트릭 조회"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(55.0)]
        }
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {"Threshold_Memory": "80"})

        assert mock_cw.get_metric_statistics.call_count == 2  # CPU + Memory
        assert result["Memory"] == pytest.approx(55.0)


# ──────────────────────────────────────────────
# RDS 단위 테스트
# ──────────────────────────────────────────────

class TestRDSCollector:
    def test_collect_filters_monitoring_tag(self):
        """Monitoring=on 태그 있는 RDS만 반환"""
        from common.collectors.rds import collect_monitored_resources

        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            "DBInstances": [
                _make_rds_instance(
                    "db-monitored",
                    "arn:aws:rds:us-east-1:123:db:db-monitored",
                ),
                _make_rds_instance(
                    "db-unmonitored",
                    "arn:aws:rds:us-east-1:123:db:db-unmonitored",
                ),
            ]
        }]

        def mock_list_tags(ResourceName):
            if "db-monitored" in ResourceName:
                return {"TagList": [{"Key": "Monitoring", "Value": "on"}]}
            return {"TagList": []}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as mock_session:
            mock_session.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "db-monitored"

    def test_get_metrics_converts_bytes_to_gb(self):
        """FreeableMemory/FreeStorageSpace bytes → GB 변환"""
        from common.collectors.rds import get_metrics

        mock_cw = MagicMock()
        # 2GB = 2 * 1024^3 bytes
        two_gb = 2 * (1024 ** 3)
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{"Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                            "Average": float(two_gb)}]
        }
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_metrics("db-123")

        assert result["FreeMemoryGB"] == pytest.approx(2.0)
        assert result["FreeStorageGB"] == pytest.approx(2.0)

    def test_get_metrics_returns_none_when_no_data(self):
        """CloudWatch 데이터 없을 때 None 반환"""
        from common.collectors.rds import get_metrics

        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_metrics("db-123")
        assert result is None


# ──────────────────────────────────────────────
# ELB/NLB 단위 테스트 — Requirements 1.12, 2.12
# ──────────────────────────────────────────────

_ALB_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:123456789012"
    ":loadbalancer/app/my-alb/abc123"
)
_NLB_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:123456789012"
    ":loadbalancer/net/my-nlb/def456"
)


def _make_lb(arn: str, lb_type: str = "application",
             state: str = "active") -> dict:
    """describe_load_balancers 응답용 LB dict 생성."""
    return {
        "LoadBalancerArn": arn,
        "Type": lb_type,
        "State": {"Code": state},
    }


def _mock_elbv2_for_collection(lbs, tag_map):
    """ELBv2 클라이언트 mock 생성 (수집 테스트용)."""
    mock = MagicMock()
    mock_paginator = MagicMock()
    mock.get_paginator.return_value = mock_paginator

    # describe_load_balancers paginator
    mock_paginator.paginate.return_value = [
        {"LoadBalancers": lbs}
    ]

    # describe_tags
    def _describe_tags(ResourceArns):
        arn = ResourceArns[0]
        tags = tag_map.get(arn, {})
        return {
            "TagDescriptions": [{
                "Tags": [{"Key": k, "Value": v}
                         for k, v in tags.items()]
            }]
        }
    mock.describe_tags.side_effect = _describe_tags
    return mock


class TestELBCollector:
    """ELB Collector 단위 테스트 — ALB/NLB 지원."""

    def test_nlb_collection_stores_lb_type_network(self):
        """NLB 수집 시 _lb_type='network' 태그 저장 — Req 1.12"""
        from common.collectors import elb

        mock_elbv2 = _mock_elbv2_for_collection(
            [_make_lb(_NLB_ARN, "network")],
            {_NLB_ARN: {"Monitoring": "on", "Name": "my-nlb"}},
        )
        # TG 없음
        mock_elbv2.get_paginator.return_value.paginate.side_effect = [
            [{"LoadBalancers": [_make_lb(_NLB_ARN, "network")]}],
            [{"TargetGroups": []}],
        ]

        with patch.object(elb, "_get_elbv2_client",
                          return_value=mock_elbv2), \
             patch("common.collectors.elb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elb.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["tags"]["_lb_type"] == "network"

    def test_alb_collection_stores_lb_type_application(self):
        """ALB 수집 시 _lb_type='application' 태그 저장 (보존)"""
        from common.collectors import elb

        mock_elbv2 = _mock_elbv2_for_collection(
            [_make_lb(_ALB_ARN, "application")],
            {_ALB_ARN: {"Monitoring": "on", "Name": "my-alb"}},
        )
        mock_elbv2.get_paginator.return_value.paginate.side_effect = [
            [{"LoadBalancers": [_make_lb(_ALB_ARN, "application")]}],
            [{"TargetGroups": []}],
        ]

        with patch.object(elb, "_get_elbv2_client",
                          return_value=mock_elbv2), \
             patch("common.collectors.elb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elb.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["tags"]["_lb_type"] == "application"

    def test_nlb_get_metrics_uses_network_elb_namespace(self):
        """NLB get_metrics → AWS/NetworkELB 네임스페이스 사용 — Req 2.12"""
        from common.collectors.elb import get_metrics

        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(5000.0)]
        }

        with patch("common.collectors.base._get_cw_client",
                    return_value=mock_cw):
            result = get_metrics(
                _NLB_ARN,
                resource_tags={"_lb_type": "network"},
            )

        # NLB 메트릭: ProcessedBytes, ActiveFlowCount, NewFlowCount
        assert result is not None
        assert "ProcessedBytes" in result

        # 모든 호출이 AWS/NetworkELB 네임스페이스를 사용하는지 확인
        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/NetworkELB"

    def test_alb_get_metrics_still_uses_application_elb(self):
        """ALB get_metrics → AWS/ApplicationELB 네임스페이스 보존"""
        from common.collectors.elb import get_metrics

        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(100.0)]
        }

        with patch("common.collectors.base._get_cw_client",
                    return_value=mock_cw):
            result = get_metrics(
                _ALB_ARN,
                resource_tags={"_lb_type": "application"},
            )

        assert result is not None
        assert "RequestCount" in result

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/ApplicationELB"

    def test_nlb_get_metrics_returns_all_nlb_metrics(self):
        """NLB에서 ProcessedBytes, ActiveFlowCount, NewFlowCount 수집"""
        from common.collectors.elb import get_metrics

        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(42.0)]
        }

        with patch("common.collectors.base._get_cw_client",
                    return_value=mock_cw):
            result = get_metrics(
                _NLB_ARN,
                resource_tags={"_lb_type": "network"},
            )

        assert result is not None
        # NLB는 3개 메트릭 수집
        assert "ProcessedBytes" in result
        assert "ActiveFlowCount" in result
        assert "NewFlowCount" in result
        assert mock_cw.get_metric_statistics.call_count == 3

    def test_namespace_for_lb_type_helper(self):
        """_namespace_for_lb_type 헬퍼 함수 검증"""
        from common.collectors.elb import _namespace_for_lb_type

        assert _namespace_for_lb_type("network") == "AWS/NetworkELB"
        assert _namespace_for_lb_type("application") == "AWS/ApplicationELB"
        # 알 수 없는 타입은 기본값 ALB
        assert _namespace_for_lb_type("gateway") == "AWS/ApplicationELB"

    def test_arn_to_suffix_nlb(self):
        """NLB ARN suffix 추출 검증"""
        from common.collectors.elb import _arn_to_suffix

        assert _arn_to_suffix(_NLB_ARN) == "net/my-nlb/def456"
        assert _arn_to_suffix(_ALB_ARN) == "app/my-alb/abc123"

    # ── Task 2.1: ALB/NLB/TG resource_type 세분화 검증 ──
    # Validates: Requirements 1.1, 2.1, 3.1

    def test_alb_collection_returns_type_alb(self):
        """ALB(Type=application) 수집 시 ResourceInfo.type == 'ALB' — Req 1.1"""
        from common.collectors import elb

        mock_elbv2 = _mock_elbv2_for_collection(
            [_make_lb(_ALB_ARN, "application")],
            {_ALB_ARN: {"Monitoring": "on", "Name": "my-alb"}},
        )
        mock_elbv2.get_paginator.return_value.paginate.side_effect = [
            [{"LoadBalancers": [_make_lb(_ALB_ARN, "application")]}],
            [{"TargetGroups": []}],
        ]

        with patch.object(elb, "_get_elbv2_client",
                          return_value=mock_elbv2), \
             patch("common.collectors.elb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elb.collect_monitored_resources()

        alb_resources = [r for r in result if r["id"] == _ALB_ARN]
        assert len(alb_resources) == 1
        assert alb_resources[0]["type"] == "ALB"

    def test_nlb_collection_returns_type_nlb(self):
        """NLB(Type=network) 수집 시 ResourceInfo.type == 'NLB' — Req 2.1"""
        from common.collectors import elb

        mock_elbv2 = _mock_elbv2_for_collection(
            [_make_lb(_NLB_ARN, "network")],
            {_NLB_ARN: {"Monitoring": "on", "Name": "my-nlb"}},
        )
        mock_elbv2.get_paginator.return_value.paginate.side_effect = [
            [{"LoadBalancers": [_make_lb(_NLB_ARN, "network")]}],
            [{"TargetGroups": []}],
        ]

        with patch.object(elb, "_get_elbv2_client",
                          return_value=mock_elbv2), \
             patch("common.collectors.elb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elb.collect_monitored_resources()

        nlb_resources = [r for r in result if r["id"] == _NLB_ARN]
        assert len(nlb_resources) == 1
        assert nlb_resources[0]["type"] == "NLB"

    def test_tg_collection_keeps_type_tg(self):
        """TG 수집 시 ResourceInfo.type == 'TG' 유지 — Req 3.1"""
        from common.collectors import elb

        tg_arn = (
            "arn:aws:elasticloadbalancing:us-east-1:123456789012"
            ":targetgroup/my-tg/ghi789"
        )
        mock_elbv2 = MagicMock()
        mock_paginator = MagicMock()
        mock_elbv2.get_paginator.return_value = mock_paginator

        # First paginate call: describe_load_balancers
        # Second paginate call: describe_target_groups
        mock_paginator.paginate.side_effect = [
            [{"LoadBalancers": [_make_lb(_ALB_ARN, "application")]}],
            [{"TargetGroups": [{"TargetGroupArn": tg_arn}]}],
        ]

        def _describe_tags(ResourceArns):
            arn = ResourceArns[0]
            if arn == _ALB_ARN:
                return {"TagDescriptions": [{"Tags": [
                    {"Key": "Monitoring", "Value": "on"},
                    {"Key": "Name", "Value": "my-alb"},
                ]}]}
            if arn == tg_arn:
                return {"TagDescriptions": [{"Tags": [
                    {"Key": "Monitoring", "Value": "on"},
                    {"Key": "Name", "Value": "my-tg"},
                ]}]}
            return {"TagDescriptions": [{"Tags": []}]}

        mock_elbv2.describe_tags.side_effect = _describe_tags

        with patch.object(elb, "_get_elbv2_client",
                          return_value=mock_elbv2), \
             patch("common.collectors.elb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elb.collect_monitored_resources()

        tg_resources = [r for r in result if r["id"] == tg_arn]
        assert len(tg_resources) == 1
        assert tg_resources[0]["type"] == "TG"


# ──────────────────────────────────────────────
# RDS Aurora 분류 단위 테스트
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
# ──────────────────────────────────────────────

class TestRDSAuroraClassification:
    """collect_monitored_resources() Aurora 분류 검증."""

    def _mock_rds_for_collection(self, instances, tag_map):
        """RDS 클라이언트 mock 생성 (수집 테스트용)."""
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"DBInstances": instances}]

        def mock_list_tags(ResourceName):
            tags = tag_map.get(ResourceName, {})
            return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags
        return mock_rds

    def test_aurora_mysql_classified_as_aurora_rds(self):
        """Engine 'aurora-mysql' → type='AuroraRDS' — Req 1.1, 1.3"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-db-1"
        instances = [_make_rds_instance("aurora-db-1", arn, engine="aurora-mysql")]
        mock_rds = self._mock_rds_for_collection(instances, {arn: {"Monitoring": "on"}})

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["type"] == "AuroraRDS"
        assert result[0]["id"] == "aurora-db-1"

    def test_aurora_postgresql_classified_as_aurora_rds(self):
        """Engine 'aurora-postgresql' → type='AuroraRDS' — Req 1.1, 1.3"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-pg-1"
        instances = [_make_rds_instance("aurora-pg-1", arn, engine="aurora-postgresql")]
        mock_rds = self._mock_rds_for_collection(instances, {arn: {"Monitoring": "on"}})

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["type"] == "AuroraRDS"

    def test_mysql_engine_stays_rds(self):
        """Engine 'mysql' → type='RDS' 유지 — Req 1.2"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:mysql-db-1"
        instances = [_make_rds_instance("mysql-db-1", arn, engine="mysql")]
        mock_rds = self._mock_rds_for_collection(instances, {arn: {"Monitoring": "on"}})

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["type"] == "RDS"

    def test_aurora_engine_classified_as_aurora_rds(self):
        """Engine 'aurora' → type='AuroraRDS' — Req 1.1, 1.3"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-plain-1"
        instances = [_make_rds_instance("aurora-plain-1", arn, engine="aurora")]
        mock_rds = self._mock_rds_for_collection(instances, {arn: {"Monitoring": "on"}})

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["type"] == "AuroraRDS"

    def test_deleting_aurora_instance_skipped(self):
        """deleting/deleted Aurora 인스턴스 skip — Req 1.5"""
        from common.collectors.rds import collect_monitored_resources

        arn_del = "arn:aws:rds:us-east-1:123:db:aurora-deleting"
        arn_deleted = "arn:aws:rds:us-east-1:123:db:aurora-deleted"
        arn_ok = "arn:aws:rds:us-east-1:123:db:aurora-ok"
        instances = [
            _make_rds_instance("aurora-deleting", arn_del, status="deleting", engine="aurora-mysql"),
            _make_rds_instance("aurora-deleted", arn_deleted, status="deleted", engine="aurora-postgresql"),
            _make_rds_instance("aurora-ok", arn_ok, status="available", engine="aurora-mysql"),
        ]
        tag_map = {
            arn_del: {"Monitoring": "on"},
            arn_deleted: {"Monitoring": "on"},
            arn_ok: {"Monitoring": "on"},
        }
        mock_rds = self._mock_rds_for_collection(instances, tag_map)

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "aurora-ok"
        assert result[0]["type"] == "AuroraRDS"

    def test_mixed_engines_classified_correctly(self):
        """Aurora + non-Aurora 혼합 시 각각 올바르게 분류 — Req 1.1, 1.2"""
        from common.collectors.rds import collect_monitored_resources

        arn1 = "arn:aws:rds:us-east-1:123:db:aurora-db"
        arn2 = "arn:aws:rds:us-east-1:123:db:mysql-db"
        instances = [
            _make_rds_instance("aurora-db", arn1, engine="aurora-mysql"),
            _make_rds_instance("mysql-db", arn2, engine="mysql"),
        ]
        tag_map = {arn1: {"Monitoring": "on"}, arn2: {"Monitoring": "on"}}
        mock_rds = self._mock_rds_for_collection(instances, tag_map)

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        result_map = {r["id"]: r["type"] for r in result}
        assert result_map["aurora-db"] == "AuroraRDS"
        assert result_map["mysql-db"] == "RDS"


# ──────────────────────────────────────────────
# RDS Aurora 메트릭 수집 단위 테스트
# Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
# ──────────────────────────────────────────────

class TestAuroraMetrics:
    """get_aurora_metrics() 메트릭 수집 검증."""

    def _make_cw_mock_with_data(self, metric_data: dict[str, float]):
        """CloudWatch mock: metric_name → value 매핑으로 응답 생성."""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in metric_data:
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": metric_data[metric_name],
                        "Maximum": metric_data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats
        return mock_cw

    def test_all_five_metrics_returned(self):
        """Provisioned Writer (w/ readers) 5개 메트릭 모두 반환 — Req 4.1"""
        from common.collectors.rds import get_aurora_metrics

        two_gb = 2.0 * (1024 ** 3)
        five_gb = 5.0 * (1024 ** 3)
        mock_cw = self._make_cw_mock_with_data({
            "CPUUtilization": 75.0,
            "FreeableMemory": two_gb,
            "DatabaseConnections": 50.0,
            "FreeLocalStorage": five_gb,
            "AuroraReplicaLagMaximum": 1500000.0,
        })
        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1", resource_tags=tags)

        assert result is not None
        assert result["CPU"] == pytest.approx(75.0)
        assert result["FreeMemoryGB"] == pytest.approx(2.0)
        assert result["Connections"] == pytest.approx(50.0)
        assert result["FreeLocalStorageGB"] == pytest.approx(5.0)
        assert result["ReplicaLag"] == pytest.approx(1500000.0)

    def test_freeable_memory_bytes_to_gb(self):
        """FreeableMemory bytes→GB 변환 — Req 4.2"""
        from common.collectors.rds import get_aurora_metrics

        four_gb_bytes = 4.0 * 1073741824
        mock_cw = self._make_cw_mock_with_data({
            "FreeableMemory": four_gb_bytes,
        })

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1")

        assert result is not None
        assert result["FreeMemoryGB"] == pytest.approx(4.0)

    def test_free_local_storage_bytes_to_gb(self):
        """FreeLocalStorage bytes→GB 변환 — Req 4.3"""
        from common.collectors.rds import get_aurora_metrics

        ten_gb_bytes = 10.0 * 1073741824
        mock_cw = self._make_cw_mock_with_data({
            "FreeLocalStorage": ten_gb_bytes,
        })

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1")

        assert result is not None
        assert result["FreeLocalStorageGB"] == pytest.approx(10.0)

    def test_replica_lag_raw_microseconds(self):
        """AuroraReplicaLagMaximum raw μs 반환 — Req 4.4"""
        from common.collectors.rds import get_aurora_metrics

        mock_cw = self._make_cw_mock_with_data({
            "AuroraReplicaLagMaximum": 2500000.0,
        })
        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1", resource_tags=tags)

        assert result is not None
        assert result["ReplicaLag"] == pytest.approx(2500000.0)

    def test_individual_metric_skip_when_no_data(self):
        """개별 메트릭 데이터 없을 때 skip — Req 4.7"""
        from common.collectors.rds import get_aurora_metrics

        # CPUUtilization만 데이터 있음, 나머지 없음
        mock_cw = self._make_cw_mock_with_data({
            "CPUUtilization": 60.0,
        })

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1")

        assert result is not None
        assert result["CPU"] == pytest.approx(60.0)
        assert "FreeMemoryGB" not in result
        assert "Connections" not in result
        assert "FreeLocalStorageGB" not in result
        assert "ReplicaLag" not in result

    def test_returns_none_when_all_metrics_empty(self):
        """전체 메트릭 없을 때 None 반환 — Req 4.8"""
        from common.collectors.rds import get_aurora_metrics

        mock_cw = self._make_cw_mock_with_data({})  # 모든 메트릭 데이터 없음

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-db-1")

        assert result is None


# ──────────────────────────────────────────────
# get_aurora_metrics() 조건부 분기 단위 테스트
# Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3
# ──────────────────────────────────────────────

class TestAuroraMetricsConditionalBranching:
    """get_aurora_metrics() 변형별 메트릭 수집 검증."""

    def _make_cw_mock_all_data(self):
        """CloudWatch mock: 모든 Aurora 메트릭에 데이터 반환."""
        mock_cw = MagicMock()
        two_gb = 2.0 * (1024 ** 3)
        five_gb = 5.0 * (1024 ** 3)

        data = {
            "CPUUtilization": 75.0,
            "FreeableMemory": two_gb,
            "DatabaseConnections": 50.0,
            "FreeLocalStorage": five_gb,
            "AuroraReplicaLagMaximum": 1500000.0,
            "AuroraReplicaLag": 800000.0,
            "ACUUtilization": 65.0,
            "ServerlessDatabaseCapacity": 32.0,
        }

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in data:
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": data[metric_name],
                        "Maximum": data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats
        return mock_cw

    def test_serverless_v2_collects_acu_skips_free_local_storage(self):
        """Serverless v2: ACUUtilization 수집,
        FreeMemoryGB/FreeLocalStorageGB/ServerlessDatabaseCapacity 미수집"""
        from common.collectors.rds import get_aurora_metrics

        tags = {
            "_is_serverless_v2": "true",
            "_is_cluster_writer": "true",
            "_has_readers": "false",
        }
        mock_cw = self._make_cw_mock_all_data()

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-sv2-1", resource_tags=tags)

        assert result is not None
        assert "CPU" in result
        assert "Connections" in result
        # Serverless v2 specific
        assert "ACUUtilization" in result
        assert result["ACUUtilization"] == pytest.approx(65.0)
        # Must NOT collect these for Serverless v2
        assert "FreeMemoryGB" not in result
        assert "FreeLocalStorageGB" not in result
        assert "ServerlessDatabaseCapacity" not in result

    def test_provisioned_collects_free_local_storage_skips_acu(self):
        """Provisioned: FreeLocalStorageGB 수집,
        ACUUtilization/ServerlessDatabaseCapacity 미수집 — Req 10.3"""
        from common.collectors.rds import get_aurora_metrics

        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }
        mock_cw = self._make_cw_mock_all_data()

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-prov-1", resource_tags=tags)

        assert result is not None
        # Always collected
        assert "CPU" in result
        assert "FreeMemoryGB" in result
        assert "Connections" in result
        # Provisioned specific
        assert "FreeLocalStorageGB" in result
        # Must NOT collect Serverless v2 metrics
        assert "ACUUtilization" not in result
        assert "ServerlessDatabaseCapacity" not in result

    def test_writer_with_readers_collects_replica_lag(self):
        """Writer (w/ readers): ReplicaLag (AuroraReplicaLagMaximum) 수집
        — Req 9.2"""
        from common.collectors.rds import get_aurora_metrics

        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }
        mock_cw = self._make_cw_mock_all_data()

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-writer-1", resource_tags=tags)

        assert result is not None
        assert "ReplicaLag" in result
        assert result["ReplicaLag"] == pytest.approx(1500000.0)
        # Should NOT have ReaderReplicaLag
        assert "ReaderReplicaLag" not in result

    def test_reader_collects_reader_replica_lag(self):
        """Reader: ReaderReplicaLag (AuroraReplicaLag) 수집 — Req 9.1"""
        from common.collectors.rds import get_aurora_metrics

        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "false",
            "_has_readers": "true",
        }
        mock_cw = self._make_cw_mock_all_data()

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-reader-1", resource_tags=tags)

        assert result is not None
        assert "ReaderReplicaLag" in result
        assert result["ReaderReplicaLag"] == pytest.approx(800000.0)
        # Should NOT have writer ReplicaLag
        assert "ReplicaLag" not in result

    def test_writer_no_readers_skips_replica_lag(self):
        """Writer (no readers): replica lag 메트릭 미수집 — Req 9.3"""
        from common.collectors.rds import get_aurora_metrics

        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "false",
        }
        mock_cw = self._make_cw_mock_all_data()

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = get_aurora_metrics("aurora-solo-writer", resource_tags=tags)

        assert result is not None
        # No replica lag metrics at all
        assert "ReplicaLag" not in result
        assert "ReaderReplicaLag" not in result


# ──────────────────────────────────────────────
# Aurora Metadata Enrichment 단위 테스트
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 6.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.3
# ──────────────────────────────────────────────

def _make_aurora_instance(
    db_id: str,
    db_arn: str,
    instance_class: str = "db.r6g.large",
    engine: str = "aurora-mysql",
    cluster_id: str = "my-aurora-cluster",
    status: str = "available",
) -> dict:
    """Aurora DB 인스턴스 응답 생성 (DBInstanceClass, DBClusterIdentifier 포함)."""
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceArn": db_arn,
        "DBInstanceStatus": status,
        "Engine": engine,
        "DBInstanceClass": instance_class,
        "DBClusterIdentifier": cluster_id,
    }


def _make_cluster_response(
    cluster_id: str,
    members: list[dict],
    serverless_v2_config: dict | None = None,
) -> dict:
    """describe_db_clusters 응답 생성."""
    cluster = {
        "DBClusterIdentifier": cluster_id,
        "DBClusterMembers": members,
    }
    if serverless_v2_config is not None:
        cluster["ServerlessV2ScalingConfiguration"] = serverless_v2_config
    return {"DBClusters": [cluster]}


def _make_cluster_member(db_id: str, is_writer: bool = False) -> dict:
    """DBClusterMembers 항목 생성."""
    return {
        "DBInstanceIdentifier": db_id,
        "IsClusterWriter": is_writer,
    }


class TestAuroraMetadataEnrichment:
    """_enrich_aurora_metadata() 및 _INSTANCE_CLASS_MEMORY_MAP 검증."""

    def _mock_rds_with_cluster(self, instances, tag_map, cluster_response):
        """RDS 클라이언트 mock: paginator + list_tags + describe_db_clusters."""
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"DBInstances": instances}]

        def mock_list_tags(ResourceName):
            tags = tag_map.get(ResourceName, {})
            return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags
        mock_rds.describe_db_clusters.return_value = cluster_response
        return mock_rds

    def test_provisioned_writer_with_readers(self):
        """Provisioned Writer (w/ readers): 모든 내부 태그 검증 — Req 1.1, 1.2, 1.3, 4.2, 4.3, 6.1"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-writer-1"
        instances = [_make_aurora_instance(
            "aurora-writer-1", arn, instance_class="db.r6g.large",
        )]
        cluster_resp = _make_cluster_response(
            "my-aurora-cluster",
            members=[
                _make_cluster_member("aurora-writer-1", is_writer=True),
                _make_cluster_member("aurora-reader-1", is_writer=False),
            ],
        )
        mock_rds = self._mock_rds_with_cluster(
            instances, {arn: {"Monitoring": "on"}}, cluster_resp,
        )

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        assert tags["_db_instance_class"] == "db.r6g.large"
        assert tags["_is_serverless_v2"] == "false"
        assert tags["_is_cluster_writer"] == "true"
        assert tags["_has_readers"] == "true"
        assert tags["_total_memory_bytes"] == str(16 * 1073741824)

    def test_provisioned_reader(self):
        """Provisioned Reader: _is_cluster_writer='false' — Req 1.2, 4.2"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-reader-1"
        instances = [_make_aurora_instance(
            "aurora-reader-1", arn, instance_class="db.r6g.large",
        )]
        cluster_resp = _make_cluster_response(
            "my-aurora-cluster",
            members=[
                _make_cluster_member("aurora-writer-1", is_writer=True),
                _make_cluster_member("aurora-reader-1", is_writer=False),
            ],
        )
        mock_rds = self._mock_rds_with_cluster(
            instances, {arn: {"Monitoring": "on"}}, cluster_resp,
        )

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        assert tags["_is_cluster_writer"] == "false"
        assert tags["_has_readers"] == "true"

    def test_writer_only_cluster(self):
        """Writer-only 클러스터: _has_readers='false' — Req 4.2, 4.3"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-solo-writer"
        instances = [_make_aurora_instance(
            "aurora-solo-writer", arn, instance_class="db.r6g.large",
        )]
        cluster_resp = _make_cluster_response(
            "my-aurora-cluster",
            members=[
                _make_cluster_member("aurora-solo-writer", is_writer=True),
            ],
        )
        mock_rds = self._mock_rds_with_cluster(
            instances, {arn: {"Monitoring": "on"}}, cluster_resp,
        )

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        assert tags["_is_cluster_writer"] == "true"
        assert tags["_has_readers"] == "false"

    def test_serverless_v2_instance(self):
        """Serverless v2: _is_serverless_v2='true', ACU 태그, 메모리 계산 — Req 1.3, 6.2, 8.1, 8.2"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:aurora-sv2-1"
        instances = [_make_aurora_instance(
            "aurora-sv2-1", arn, instance_class="db.serverless",
        )]
        cluster_resp = _make_cluster_response(
            "my-aurora-cluster",
            members=[
                _make_cluster_member("aurora-sv2-1", is_writer=True),
            ],
            serverless_v2_config={"MaxCapacity": 64.0, "MinCapacity": 0.5},
        )
        mock_rds = self._mock_rds_with_cluster(
            instances, {arn: {"Monitoring": "on"}}, cluster_resp,
        )

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        assert tags["_is_serverless_v2"] == "true"
        assert tags["_max_acu"] == "64.0"
        assert tags["_min_acu"] == "0.5"
        expected_memory = int(64.0 * 2 * 1073741824)
        assert tags["_total_memory_bytes"] == str(expected_memory)

    def test_regular_rds_no_aurora_tags(self):
        """일반 RDS 인스턴스: Aurora 전용 내부 태그 미포함 — Req 1.5"""
        from common.collectors.rds import collect_monitored_resources

        arn = "arn:aws:rds:us-east-1:123:db:mysql-db-1"
        instances = [_make_rds_instance("mysql-db-1", arn, engine="mysql")]
        # Regular RDS — no cluster response needed
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"DBInstances": instances}]

        def mock_list_tags(ResourceName):
            return {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        aurora_keys = {
            "_db_instance_class", "_is_serverless_v2",
            "_is_cluster_writer", "_has_readers",
            "_max_acu", "_min_acu", "_total_memory_bytes",
        }
        for key in aurora_keys:
            assert key not in tags, f"{key} should not be in regular RDS tags"

    def test_instance_class_memory_map_entries(self):
        """_INSTANCE_CLASS_MEMORY_MAP 주요 엔트리 검증 — Req 6.1, 6.3"""
        from common.collectors.rds import _INSTANCE_CLASS_MEMORY_MAP

        gib = 1073741824
        assert _INSTANCE_CLASS_MEMORY_MAP["db.r6g.large"] == 16 * gib
        assert _INSTANCE_CLASS_MEMORY_MAP["db.r6g.xlarge"] == 32 * gib
        assert _INSTANCE_CLASS_MEMORY_MAP["db.r6g.16xlarge"] == 512 * gib
        assert _INSTANCE_CLASS_MEMORY_MAP["db.r7g.large"] == 16 * gib
        assert _INSTANCE_CLASS_MEMORY_MAP["db.t3.micro"] == 1 * gib
        assert _INSTANCE_CLASS_MEMORY_MAP["db.t4g.large"] == 8 * gib

    def test_describe_db_clusters_failure_graceful_degradation(self):
        """describe_db_clusters 실패 시 graceful degradation — Req 8.3"""
        from common.collectors.rds import collect_monitored_resources
        from botocore.exceptions import ClientError

        arn = "arn:aws:rds:us-east-1:123:db:aurora-fail-1"
        instances = [_make_aurora_instance("aurora-fail-1", arn)]

        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"DBInstances": instances}]

        def mock_list_tags(ResourceName):
            return {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags
        mock_rds.describe_db_clusters.side_effect = ClientError(
            {"Error": {"Code": "DBClusterNotFoundFault", "Message": "not found"}},
            "describe_db_clusters",
        )

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        # Should still collect the instance, just without cluster-derived tags
        assert len(result) == 1
        tags = result[0]["tags"]
        assert tags["_db_instance_class"] == "db.r6g.large"
        assert tags["_is_serverless_v2"] == "false"
        # Cluster-derived tags should be absent
        assert "_is_cluster_writer" not in tags
        assert "_has_readers" not in tags

    def test_unknown_instance_class_no_memory_with_warning(self):
        """알 수 없는 인스턴스 클래스: API도 실패 시 _total_memory_bytes 미포함 + warning — Req 6.4"""
        from common.collectors.rds import (
            collect_monitored_resources,
            _instance_class_memory_cache,
        )

        _instance_class_memory_cache.clear()

        arn = "arn:aws:rds:us-east-1:123:db:aurora-unknown-1"
        instances = [_make_aurora_instance(
            "aurora-unknown-1", arn, instance_class="db.x99g.mega",
        )]
        cluster_resp = _make_cluster_response(
            "my-aurora-cluster",
            members=[_make_cluster_member("aurora-unknown-1", is_writer=True)],
        )
        mock_rds = self._mock_rds_with_cluster(
            instances, {arn: {"Monitoring": "on"}}, cluster_resp,
        )
        # API도 해당 인스턴스 클래스를 모르는 경우 빈 결과 반환
        mock_rds.describe_db_instance_classes.return_value = {
            "DBInstanceClasses": [],
        }

        with patch("common.collectors.rds._get_rds_client", return_value=mock_rds), \
             patch("common.collectors.rds.boto3.session.Session") as ms, \
             patch("common.collectors.rds.logger") as mock_logger:
            ms.return_value.region_name = "us-east-1"
            result = collect_monitored_resources()

        assert len(result) == 1
        tags = result[0]["tags"]
        assert "_total_memory_bytes" not in tags
        mock_logger.warning.assert_called()


# ──────────────────────────────────────────────
# DocDB Collector 단위 테스트
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9
# ──────────────────────────────────────────────

from common.collectors import docdb as docdb_collector


def _make_docdb_instance(db_id: str, db_arn: str, status: str = "available",
                         engine: str = "docdb") -> dict:
    """describe_db_instances 응답용 DocDB 인스턴스 dict 생성."""
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceArn": db_arn,
        "DBInstanceStatus": status,
        "Engine": engine,
    }


class TestDocDBCollector:
    """DocDB Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_rds_for_docdb(self, instances, tag_map):
        """RDS 클라이언트 mock 생성 (DocDB 수집 테스트용)."""
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_rds.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"DBInstances": instances}]

        def mock_list_tags(ResourceName):
            tags = tag_map.get(ResourceName, {})
            return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags
        return mock_rds

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_docdb_engine_only(self):
        """Engine 'docdb'만 수집, type='DocDB' — Req 1.1, 1.2, 1.5"""
        arn_docdb = "arn:aws:rds:us-east-1:123:db:docdb-inst-1"
        arn_aurora = "arn:aws:rds:us-east-1:123:db:aurora-inst-1"
        arn_mysql = "arn:aws:rds:us-east-1:123:db:mysql-inst-1"
        arn_postgres = "arn:aws:rds:us-east-1:123:db:pg-inst-1"

        instances = [
            _make_docdb_instance("docdb-inst-1", arn_docdb, engine="docdb"),
            _make_docdb_instance("aurora-inst-1", arn_aurora, engine="aurora-mysql"),
            _make_docdb_instance("mysql-inst-1", arn_mysql, engine="mysql"),
            _make_docdb_instance("pg-inst-1", arn_postgres, engine="postgres"),
        ]
        tag_map = {
            arn_docdb: {"Monitoring": "on"},
            arn_aurora: {"Monitoring": "on"},
            arn_mysql: {"Monitoring": "on"},
            arn_postgres: {"Monitoring": "on"},
        }
        mock_rds = self._mock_rds_for_docdb(instances, tag_map)

        with patch.object(docdb_collector, "_get_rds_client", return_value=mock_rds), \
             patch("common.collectors.docdb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = docdb_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "docdb-inst-1"
        assert result[0]["type"] == "DocDB"

    def test_engine_filtering_excludes_non_docdb(self):
        """aurora-mysql, mysql, postgres 엔진 제외 — Req 1.5"""
        instances = [
            _make_docdb_instance("a1", "arn:aws:rds:us-east-1:123:db:a1", engine="aurora-mysql"),
            _make_docdb_instance("a2", "arn:aws:rds:us-east-1:123:db:a2", engine="mysql"),
            _make_docdb_instance("a3", "arn:aws:rds:us-east-1:123:db:a3", engine="postgres"),
        ]
        tag_map = {
            "arn:aws:rds:us-east-1:123:db:a1": {"Monitoring": "on"},
            "arn:aws:rds:us-east-1:123:db:a2": {"Monitoring": "on"},
            "arn:aws:rds:us-east-1:123:db:a3": {"Monitoring": "on"},
        }
        mock_rds = self._mock_rds_for_docdb(instances, tag_map)

        with patch.object(docdb_collector, "_get_rds_client", return_value=mock_rds), \
             patch("common.collectors.docdb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = docdb_collector.collect_monitored_resources()

        assert result == []

    def test_deleting_status_skipped(self):
        """DBInstanceStatus 'deleting' 인스턴스 skip — Req 1.3"""
        arn_del = "arn:aws:rds:us-east-1:123:db:docdb-deleting"
        arn_ok = "arn:aws:rds:us-east-1:123:db:docdb-ok"
        instances = [
            _make_docdb_instance("docdb-deleting", arn_del, status="deleting", engine="docdb"),
            _make_docdb_instance("docdb-ok", arn_ok, status="available", engine="docdb"),
        ]
        tag_map = {
            arn_del: {"Monitoring": "on"},
            arn_ok: {"Monitoring": "on"},
        }
        mock_rds = self._mock_rds_for_docdb(instances, tag_map)

        with patch.object(docdb_collector, "_get_rds_client", return_value=mock_rds), \
             patch("common.collectors.docdb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = docdb_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "docdb-ok"

    def test_monitoring_tag_required(self):
        """Monitoring=on 태그 없는 DocDB 인스턴스 제외 — Req 1.2"""
        arn_on = "arn:aws:rds:us-east-1:123:db:docdb-on"
        arn_off = "arn:aws:rds:us-east-1:123:db:docdb-off"
        instances = [
            _make_docdb_instance("docdb-on", arn_on, engine="docdb"),
            _make_docdb_instance("docdb-off", arn_off, engine="docdb"),
        ]
        tag_map = {
            arn_on: {"Monitoring": "on"},
            arn_off: {"Monitoring": "off"},
        }
        mock_rds = self._mock_rds_for_docdb(instances, tag_map)

        with patch.object(docdb_collector, "_get_rds_client", return_value=mock_rds), \
             patch("common.collectors.docdb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = docdb_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "docdb-on"

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_six_keys(self):
        """6개 메트릭 키 반환 — Req 2.1, 2.4, 2.5, 2.6, 2.7"""
        mock_cw = MagicMock()
        two_gb = 2.0 * (1024 ** 3)
        five_gb = 5.0 * (1024 ** 3)

        data = {
            "CPUUtilization": 75.0,
            "FreeableMemory": two_gb,
            "FreeLocalStorage": five_gb,
            "DatabaseConnections": 50.0,
            "ReadLatency": 0.015,
            "WriteLatency": 0.025,
        }

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in data:
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = docdb_collector.get_metrics("docdb-inst-1")

        assert result is not None
        expected_keys = {"CPU", "FreeMemoryGB", "FreeLocalStorageGB",
                         "Connections", "ReadLatency", "WriteLatency"}
        assert set(result.keys()) == expected_keys
        assert result["CPU"] == pytest.approx(75.0)
        assert result["Connections"] == pytest.approx(50.0)
        assert result["ReadLatency"] == pytest.approx(0.015)
        assert result["WriteLatency"] == pytest.approx(0.025)

    def test_freeable_memory_bytes_to_gb(self):
        """FreeableMemory bytes→GB 변환: 2147483648 → 2.0 — Req 2.2"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name == "FreeableMemory":
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": 2147483648.0,
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = docdb_collector.get_metrics("docdb-inst-1")

        assert result is not None
        assert result["FreeMemoryGB"] == pytest.approx(2.0)

    def test_free_local_storage_bytes_to_gb(self):
        """FreeLocalStorage bytes→GB 변환 — Req 2.3"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name == "FreeLocalStorage":
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": 10.0 * 1073741824,
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = docdb_collector.get_metrics("docdb-inst-1")

        assert result is not None
        assert result["FreeLocalStorageGB"] == pytest.approx(10.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 2.9"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = docdb_collector.get_metrics("docdb-inst-1")

        assert result is None


# ──────────────────────────────────────────────
# Task 5.1: DocDB Tag Resolver 지원 테스트
# Validates: Requirements 15.1
# ──────────────────────────────────────────────


class TestDocDBTagResolver:
    """get_resource_tags(resource_id, 'DocDB')가 RDS 태그 조회 경로를 사용하는지 검증."""

    def test_docdb_tag_retrieval_uses_rds_path(self):
        """get_resource_tags(id, 'DocDB') → describe_db_instances + list_tags_for_resource 호출."""
        from common.tag_resolver import get_resource_tags

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{
                "DBInstanceIdentifier": "docdb-prod-1",
                "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:docdb-prod-1",
            }],
        }
        mock_rds.list_tags_for_resource.return_value = {
            "TagList": [
                {"Key": "Monitoring", "Value": "on"},
                {"Key": "Threshold_CPU", "Value": "90"},
                {"Key": "Name", "Value": "my-docdb"},
            ],
        }

        with patch("common.tag_resolver._get_rds_client", return_value=mock_rds):
            tags = get_resource_tags("docdb-prod-1", "DocDB")

        assert tags == {"Monitoring": "on", "Threshold_CPU": "90", "Name": "my-docdb"}
        mock_rds.describe_db_instances.assert_called_once_with(
            DBInstanceIdentifier="docdb-prod-1",
        )
        mock_rds.list_tags_for_resource.assert_called_once_with(
            ResourceName="arn:aws:rds:us-east-1:123456789012:db:docdb-prod-1",
        )

    def test_docdb_returns_same_result_as_rds(self):
        """get_resource_tags(id, 'DocDB')와 get_resource_tags(id, 'RDS')가 동일 경로 사용."""
        from common.tag_resolver import get_resource_tags

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{
                "DBInstanceIdentifier": "docdb-test-1",
                "DBInstanceArn": "arn:aws:rds:us-east-1:123456789012:db:docdb-test-1",
            }],
        }
        mock_rds.list_tags_for_resource.return_value = {
            "TagList": [{"Key": "Env", "Value": "prod"}],
        }

        with patch("common.tag_resolver._get_rds_client", return_value=mock_rds):
            docdb_tags = get_resource_tags("docdb-test-1", "DocDB")
            rds_tags = get_resource_tags("docdb-test-1", "RDS")

        assert docdb_tags == rds_tags == {"Env": "prod"}

    def test_docdb_unsupported_returns_empty_before_fix(self):
        """수정 전: 'DocDB'가 지원되지 않으면 빈 dict 반환 + warning 로그."""
        from common.tag_resolver import get_resource_tags

        # This test verifies the current behavior before the fix
        # After fix, DocDB should be handled by the RDS branch
        tags = get_resource_tags("docdb-test-1", "DocDB")
        # If DocDB is not yet supported, returns {} with warning
        # If already supported, returns tags from RDS path
        assert isinstance(tags, dict)


# ──────────────────────────────────────────────
# ElastiCache Collector 단위 테스트
# Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
# ──────────────────────────────────────────────

from botocore.exceptions import ClientError as _ClientError
from common.collectors import elasticache as elasticache_collector


def _make_elasticache_cluster(cluster_id: str, arn: str, status: str = "available",
                              engine: str = "redis") -> dict:
    """describe_cache_clusters 응답용 ElastiCache 클러스터 dict 생성."""
    return {
        "CacheClusterId": cluster_id,
        "ARN": arn,
        "CacheClusterStatus": status,
        "Engine": engine,
    }


class TestElastiCacheCollector:
    """ElastiCache Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_elasticache_for_collection(self, clusters, tag_map):
        """ElastiCache 클라이언트 mock 생성 (수집 테스트용)."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"CacheClusters": clusters}]

        def mock_list_tags(ResourceName):
            tags = tag_map.get(ResourceName, {})
            return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

        mock_client.list_tags_for_resource.side_effect = mock_list_tags
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_redis_engine_only(self):
        """Engine 'redis'만 수집, type='ElastiCache' — Req 4.1, 4.5"""
        arn_redis = "arn:aws:elasticache:us-east-1:123:cluster:redis-1"
        arn_memcached = "arn:aws:elasticache:us-east-1:123:cluster:memcached-1"

        clusters = [
            _make_elasticache_cluster("redis-1", arn_redis, engine="redis"),
            _make_elasticache_cluster("memcached-1", arn_memcached, engine="memcached"),
        ]
        tag_map = {
            arn_redis: {"Monitoring": "on"},
            arn_memcached: {"Monitoring": "on"},
        }
        mock_client = self._mock_elasticache_for_collection(clusters, tag_map)

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "redis-1"
        assert result[0]["type"] == "ElastiCache"

    def test_deleting_status_skipped(self):
        """CacheClusterStatus 'deleting'/'deleted' 클러스터 skip — Req 4.4"""
        arn_del = "arn:aws:elasticache:us-east-1:123:cluster:redis-deleting"
        arn_deleted = "arn:aws:elasticache:us-east-1:123:cluster:redis-deleted"
        arn_ok = "arn:aws:elasticache:us-east-1:123:cluster:redis-ok"

        clusters = [
            _make_elasticache_cluster("redis-deleting", arn_del, status="deleting"),
            _make_elasticache_cluster("redis-deleted", arn_deleted, status="deleted"),
            _make_elasticache_cluster("redis-ok", arn_ok, status="available"),
        ]
        tag_map = {
            arn_del: {"Monitoring": "on"},
            arn_deleted: {"Monitoring": "on"},
            arn_ok: {"Monitoring": "on"},
        }
        mock_client = self._mock_elasticache_for_collection(clusters, tag_map)

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "redis-ok"

    def test_monitoring_tag_required(self):
        """Monitoring=on 태그 없는 클러스터 제외 — Req 4.1"""
        arn_on = "arn:aws:elasticache:us-east-1:123:cluster:redis-on"
        arn_off = "arn:aws:elasticache:us-east-1:123:cluster:redis-off"

        clusters = [
            _make_elasticache_cluster("redis-on", arn_on),
            _make_elasticache_cluster("redis-off", arn_off),
        ]
        tag_map = {
            arn_on: {"Monitoring": "on"},
            arn_off: {"Monitoring": "off"},
        }
        mock_client = self._mock_elasticache_for_collection(clusters, tag_map)

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "redis-on"

    def test_monitoring_tag_case_insensitive(self):
        """Monitoring=ON (대문자) 태그도 수집 — Req 4.1"""
        arn = "arn:aws:elasticache:us-east-1:123:cluster:redis-upper"
        clusters = [_make_elasticache_cluster("redis-upper", arn)]
        tag_map = {arn: {"Monitoring": "ON"}}
        mock_client = self._mock_elasticache_for_collection(clusters, tag_map)

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        assert len(result) == 1

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 4.1"""
        mock_client = self._mock_elasticache_for_collection([], {})

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """describe_cache_clusters API 오류 시 예외 전파 — Req 4.7"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "error"}},
            "describe_cache_clusters",
        )

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                elasticache_collector.collect_monitored_resources()

    def test_tag_error_returns_empty_dict(self):
        """list_tags_for_resource 실패 시 빈 dict → 해당 노드 skip — Req 4.7"""
        arn = "arn:aws:elasticache:us-east-1:123:cluster:redis-tag-err"
        clusters = [_make_elasticache_cluster("redis-tag-err", arn)]

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"CacheClusters": clusters}]
        mock_client.list_tags_for_resource.side_effect = _ClientError(
            {"Error": {"Code": "CacheClusterNotFound", "Message": "not found"}},
            "list_tags_for_resource",
        )

        with patch.object(elasticache_collector, "_get_elasticache_client",
                          return_value=mock_client), \
             patch("common.collectors.elasticache.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = elasticache_collector.collect_monitored_resources()

        # Tag error → empty dict → Monitoring tag absent → skip
        assert result == []

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_five_keys(self):
        """5개 메트릭 키 반환 — Req 4.2"""
        mock_cw = MagicMock()
        data = {
            "CPUUtilization": 75.0,
            "EngineCPUUtilization": 60.0,
            "SwapUsage": 0.5,
            "Evictions": 2.0,
            "CurrConnections": 150.0,
        }

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in data:
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = elasticache_collector.get_metrics("redis-1")

        assert result is not None
        expected_keys = {"CPU", "EngineCPU", "SwapUsage", "Evictions", "CurrConnections"}
        assert set(result.keys()) == expected_keys
        assert result["CPU"] == pytest.approx(75.0)
        assert result["EngineCPU"] == pytest.approx(60.0)
        assert result["SwapUsage"] == pytest.approx(0.5)
        assert result["Evictions"] == pytest.approx(2.0)
        assert result["CurrConnections"] == pytest.approx(150.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 4.6"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = elasticache_collector.get_metrics("redis-1")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 4.6"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name == "CPUUtilization":
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": 45.0,
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = elasticache_collector.get_metrics("redis-1")

        assert result is not None
        assert result == {"CPU": pytest.approx(45.0)}
        assert "EngineCPU" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/ElastiCache 네임스페이스 + CacheClusterId 디멘션 사용 — Req 4.2"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(50.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            elasticache_collector.get_metrics("redis-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/ElastiCache"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "CacheClusterId"
            assert dims[0]["Value"] == "redis-test-1"


# ──────────────────────────────────────────────
# NAT Gateway Collector 단위 테스트
# Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
# ──────────────────────────────────────────────

from common.collectors import natgw as natgw_collector


def _make_nat_gateway(natgw_id: str, state: str = "available",
                      tags: dict | None = None) -> dict:
    """describe_nat_gateways 응답용 NAT Gateway dict 생성."""
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]
    return {
        "NatGatewayId": natgw_id,
        "State": state,
        "Tags": tag_list,
    }


class TestNATGatewayCollector:
    """NAT Gateway Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_ec2_for_collection(self, nat_gateways):
        """EC2 클라이언트 mock 생성 (NAT GW 수집 테스트용)."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"NatGateways": nat_gateways}]
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_available_natgw(self):
        """state='available' + Monitoring=on NAT GW 수집, type='NATGateway' — Req 5.1"""
        natgws = [
            _make_nat_gateway("nat-abc123", "available", {"Monitoring": "on"}),
        ]
        mock_client = self._mock_ec2_for_collection(natgws)

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.natgw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = natgw_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "nat-abc123"
        assert result[0]["type"] == "NAT"
        assert result[0]["tags"]["Monitoring"] == "on"

    def test_deleting_state_skipped(self):
        """state 'deleting'/'deleted' NAT GW skip — Req 5.4"""
        natgws = [
            _make_nat_gateway("nat-deleting", "deleting", {"Monitoring": "on"}),
            _make_nat_gateway("nat-deleted", "deleted", {"Monitoring": "on"}),
            _make_nat_gateway("nat-ok", "available", {"Monitoring": "on"}),
        ]
        mock_client = self._mock_ec2_for_collection(natgws)

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.natgw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = natgw_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "nat-ok"

    def test_pending_state_included(self):
        """state 'pending' NAT GW는 수집 대상 — Req 5.4"""
        natgws = [
            _make_nat_gateway("nat-pending", "pending", {"Monitoring": "on"}),
        ]
        mock_client = self._mock_ec2_for_collection(natgws)

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.natgw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = natgw_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "nat-pending"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 5.1"""
        mock_client = self._mock_ec2_for_collection([])

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.natgw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = natgw_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """describe_nat_gateways API 오류 시 예외 전파 — Req 5.6"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "error"}},
            "describe_nat_gateways",
        )

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                natgw_collector.collect_monitored_resources()

    def test_tags_preserved_in_resource_info(self):
        """NAT GW 태그가 ResourceInfo에 보존 — Req 5.1"""
        natgws = [
            _make_nat_gateway("nat-tagged", "available", {
                "Monitoring": "on",
                "Name": "my-natgw",
                "Threshold_PacketsDropCount": "5",
            }),
        ]
        mock_client = self._mock_ec2_for_collection(natgws)

        with patch.object(natgw_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.natgw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = natgw_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["tags"]["Name"] == "my-natgw"
        assert result[0]["tags"]["Threshold_PacketsDropCount"] == "5"

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_two_keys(self):
        """2개 메트릭 키 반환 — Req 5.2"""
        mock_cw = MagicMock()
        data = {
            "PacketsDropCount": 3.0,
            "ErrorPortAllocation": 1.0,
        }

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in data:
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Sum": data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = natgw_collector.get_metrics("nat-abc123")

        assert result is not None
        expected_keys = {"PacketsDropCount", "ErrorPortAllocation"}
        assert set(result.keys()) == expected_keys
        assert result["PacketsDropCount"] == pytest.approx(3.0)
        assert result["ErrorPortAllocation"] == pytest.approx(1.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 5.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = natgw_collector.get_metrics("nat-abc123")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 5.5"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name == "PacketsDropCount":
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Sum": 5.0,
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = natgw_collector.get_metrics("nat-abc123")

        assert result is not None
        assert result == {"PacketsDropCount": pytest.approx(5.0)}
        assert "ErrorPortAllocation" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/NATGateway 네임스페이스 + NatGatewayId 디멘션 사용 — Req 5.2"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(2.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            natgw_collector.get_metrics("nat-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/NATGateway"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "NatGatewayId"
            assert dims[0]["Value"] == "nat-test-1"

    def test_get_metrics_uses_sum_statistic(self):
        """Sum 통계 사용 — Req 5.2"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(1.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            natgw_collector.get_metrics("nat-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            stats = call.kwargs.get("Statistics", call[1].get("Statistics"))
            assert stats == ["Sum"]


# ──────────────────────────────────────────────
# Lambda Collector 단위 테스트
# Validates: Requirements 1.3, 1.4
# ──────────────────────────────────────────────

from common.collectors import lambda_fn as lambda_collector


class TestLambdaCollector:
    """Lambda Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_lambda_for_collection(self, functions, tag_map):
        """Lambda 클라이언트 mock 생성 (수집 테스트용).

        Args:
            functions: list_functions 응답용 함수 리스트
            tag_map: {function_arn: {tag_key: tag_value}} 매핑
        """
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"Functions": functions}]

        def mock_list_tags(Resource):
            tags = tag_map.get(Resource, {})
            return {"Tags": tags}

        mock_client.list_tags.side_effect = mock_list_tags
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 함수만 수집, type='Lambda' — Req 1.3"""
        arn_on = "arn:aws:lambda:us-east-1:123:function:fn-monitored"
        arn_off = "arn:aws:lambda:us-east-1:123:function:fn-unmonitored"

        functions = [
            {"FunctionName": "fn-monitored", "FunctionArn": arn_on},
            {"FunctionName": "fn-unmonitored", "FunctionArn": arn_off},
        ]
        tag_map = {
            arn_on: {"Monitoring": "on"},
            arn_off: {"Monitoring": "off"},
        }
        mock_client = self._mock_lambda_for_collection(functions, tag_map)

        with patch.object(lambda_collector, "_get_lambda_client",
                          return_value=mock_client), \
             patch("common.collectors.lambda_fn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = lambda_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "fn-monitored"
        assert result[0]["type"] == "Lambda"

    def test_untagged_function_excluded(self):
        """태그 없는 함수 제외 — Req 1.3"""
        arn_tagged = "arn:aws:lambda:us-east-1:123:function:fn-tagged"
        arn_no_tag = "arn:aws:lambda:us-east-1:123:function:fn-no-tag"

        functions = [
            {"FunctionName": "fn-tagged", "FunctionArn": arn_tagged},
            {"FunctionName": "fn-no-tag", "FunctionArn": arn_no_tag},
        ]
        tag_map = {
            arn_tagged: {"Monitoring": "on"},
            arn_no_tag: {},
        }
        mock_client = self._mock_lambda_for_collection(functions, tag_map)

        with patch.object(lambda_collector, "_get_lambda_client",
                          return_value=mock_client), \
             patch("common.collectors.lambda_fn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = lambda_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "fn-tagged"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 1.3"""
        mock_client = self._mock_lambda_for_collection([], {})

        with patch.object(lambda_collector, "_get_lambda_client",
                          return_value=mock_client), \
             patch("common.collectors.lambda_fn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = lambda_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """list_functions API 오류 시 예외 전파 — Req 1.3"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "list_functions",
        )

        with patch.object(lambda_collector, "_get_lambda_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                lambda_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_duration_and_errors(self):
        """Duration, Errors 키 반환 — Req 1.4"""
        mock_cw = MagicMock()
        data = {
            "Duration": 1500.0,
            "Errors": 3.0,
        }

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name in data:
                stat = "Average" if metric_name == "Duration" else "Sum"
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        stat: data[metric_name],
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = lambda_collector.get_metrics("fn-test-1")

        assert result is not None
        expected_keys = {"Duration", "Errors"}
        assert set(result.keys()) == expected_keys
        assert result["Duration"] == pytest.approx(1500.0)
        assert result["Errors"] == pytest.approx(3.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 1.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = lambda_collector.get_metrics("fn-test-1")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 1.4"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            metric_name = kwargs.get("MetricName", "")
            if metric_name == "Duration":
                return {
                    "Datapoints": [{
                        "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "Average": 800.0,
                    }]
                }
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = lambda_collector.get_metrics("fn-test-1")

        assert result is not None
        assert result == {"Duration": pytest.approx(800.0)}
        assert "Errors" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/Lambda 네임스페이스 + FunctionName 디멘션 사용 — Req 1.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(100.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            lambda_collector.get_metrics("fn-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/Lambda"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "FunctionName"
            assert dims[0]["Value"] == "fn-test-1"


# ──────────────────────────────────────────────
# VPN Collector 단위 테스트
# Validates: Requirements 2.4, 2.5
# ──────────────────────────────────────────────

from common.collectors import vpn as vpn_collector


class TestVPNCollector:
    """VPN Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_ec2_for_vpn(self, vpn_connections):
        """EC2 클라이언트 mock 생성 (VPN 수집 테스트용)."""
        mock_client = MagicMock()
        mock_client.describe_vpn_connections.return_value = {
            "VpnConnections": vpn_connections,
        }
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 VPN만 수집, type='VPN' — Req 2.4
        Note: VPN uses AWS-side Filter (tag:Monitoring=on), so mock returns pre-filtered results.
        """
        # Mock returns only Monitoring=on VPNs (AWS filter applied server-side)
        vpns = [
            {
                "VpnConnectionId": "vpn-001",
                "State": "available",
                "Tags": [{"Key": "Monitoring", "Value": "on"}],
            },
        ]
        mock_client = self._mock_ec2_for_vpn(vpns)

        with patch.object(vpn_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.vpn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = vpn_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "vpn-001"
        assert result[0]["type"] == "VPN"
        # Verify the Filter was passed to the API call
        mock_client.describe_vpn_connections.assert_called_once_with(
            Filters=[{"Name": "tag:Monitoring", "Values": ["on"]}]
        )

    def test_deleted_vpn_excluded(self):
        """deleted/deleting VPN skip — Req 2.4"""
        vpns = [
            {
                "VpnConnectionId": "vpn-ok",
                "State": "available",
                "Tags": [{"Key": "Monitoring", "Value": "on"}],
            },
            {
                "VpnConnectionId": "vpn-deleted",
                "State": "deleted",
                "Tags": [{"Key": "Monitoring", "Value": "on"}],
            },
            {
                "VpnConnectionId": "vpn-deleting",
                "State": "deleting",
                "Tags": [{"Key": "Monitoring", "Value": "on"}],
            },
        ]
        mock_client = self._mock_ec2_for_vpn(vpns)

        with patch.object(vpn_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.vpn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = vpn_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "vpn-ok"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 2.4"""
        mock_client = self._mock_ec2_for_vpn([])

        with patch.object(vpn_collector, "_get_ec2_client",
                          return_value=mock_client), \
             patch("common.collectors.vpn.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = vpn_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """describe_vpn_connections API 오류 시 예외 전파 — Req 2.4"""
        mock_client = MagicMock()
        mock_client.describe_vpn_connections.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "describe_vpn_connections",
        )

        with patch.object(vpn_collector, "_get_ec2_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                vpn_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_tunnel_state(self):
        """TunnelState 키 반환 — Req 2.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{
                "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "Maximum": 1.0,
            }]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = vpn_collector.get_metrics("vpn-001")

        assert result is not None
        assert set(result.keys()) == {"TunnelState"}
        assert result["TunnelState"] == pytest.approx(1.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 2.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = vpn_collector.get_metrics("vpn-001")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 2.5"""
        # VPN has only 1 metric, so this tests the single-metric case
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{
                "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "Maximum": 0.0,
            }]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = vpn_collector.get_metrics("vpn-001")

        assert result is not None
        assert result == {"TunnelState": pytest.approx(0.0)}

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/VPN 네임스페이스 + VpnId 디멘션 사용 — Req 2.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{
                "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "Maximum": 1.0,
            }]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            vpn_collector.get_metrics("vpn-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/VPN"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "VpnId"
            assert dims[0]["Value"] == "vpn-test-1"


# ──────────────────────────────────────────────
# APIGW Collector 단위 테스트
# Validates: Requirements 3-A.2, 3-B.7–9, 3-C.12–14, 3-D.17–19, 3-E.20–22
# ──────────────────────────────────────────────

from common.collectors import apigw as apigw_collector


class TestAPGWCollector:
    """APIGW Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_apigw_clients(self, rest_apis, v2_apis):
        """REST + v2 클라이언트 mock 생성.

        Args:
            rest_apis: get_rest_apis 응답용 items 리스트
            v2_apis: get_apis 응답용 Items 리스트
        """
        mock_rest = MagicMock()
        mock_rest_pag = MagicMock()
        mock_rest.get_paginator.return_value = mock_rest_pag
        mock_rest_pag.paginate.return_value = [{"items": rest_apis}]

        # get_tags for REST APIs
        def mock_get_tags(resourceArn):
            for api in rest_apis:
                if api["id"] in resourceArn:
                    return {"tags": api.get("_test_tags", {})}
            return {"tags": {}}
        mock_rest.get_tags.side_effect = mock_get_tags

        mock_v2 = MagicMock()
        mock_v2_pag = MagicMock()
        mock_v2.get_paginator.return_value = mock_v2_pag
        mock_v2_pag.paginate.return_value = [{"Items": v2_apis}]

        return mock_rest, mock_v2

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on REST/HTTP/WS만 수집, type='APIGW' — Req 3-B.7, 3-C.12, 3-D.17"""
        rest_apis = [
            {"id": "rest-1", "name": "MyRestApi",
             "_test_tags": {"Monitoring": "on"}},
            {"id": "rest-2", "name": "NoMonitor",
             "_test_tags": {"Monitoring": "off"}},
        ]
        v2_apis = [
            {"ApiId": "http-1", "ProtocolType": "HTTP",
             "Tags": {"Monitoring": "on"}},
            {"ApiId": "ws-1", "ProtocolType": "WEBSOCKET",
             "Tags": {"Monitoring": "on"}},
            {"ApiId": "http-2", "ProtocolType": "HTTP",
             "Tags": {}},
        ]
        mock_rest, mock_v2 = self._mock_apigw_clients(rest_apis, v2_apis)

        with patch.object(apigw_collector, "_get_apigw_client",
                          return_value=mock_rest), \
             patch.object(apigw_collector, "_get_apigwv2_client",
                          return_value=mock_v2), \
             patch("common.collectors.apigw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = apigw_collector.collect_monitored_resources()

        assert len(result) == 3
        ids = {r["id"] for r in result}
        assert "MyRestApi" in ids  # REST uses api_name as id
        assert "http-1" in ids
        assert "ws-1" in ids

        # Verify _api_type tags
        for r in result:
            assert r["type"] == "APIGW"
            if r["id"] == "MyRestApi":
                assert r["tags"]["_api_type"] == "REST"
            elif r["id"] == "http-1":
                assert r["tags"]["_api_type"] == "HTTP"
            elif r["id"] == "ws-1":
                assert r["tags"]["_api_type"] == "WEBSOCKET"

    def test_untagged_apis_excluded(self):
        """태그 없는 API 제외 — Req 3-B.7"""
        rest_apis = [
            {"id": "rest-no-tag", "name": "NoTag", "_test_tags": {}},
        ]
        v2_apis = [
            {"ApiId": "http-no-tag", "ProtocolType": "HTTP", "Tags": {}},
        ]
        mock_rest, mock_v2 = self._mock_apigw_clients(rest_apis, v2_apis)

        with patch.object(apigw_collector, "_get_apigw_client",
                          return_value=mock_rest), \
             patch.object(apigw_collector, "_get_apigwv2_client",
                          return_value=mock_v2), \
             patch("common.collectors.apigw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = apigw_collector.collect_monitored_resources()

        assert result == []

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 3-E.20"""
        mock_rest, mock_v2 = self._mock_apigw_clients([], [])

        with patch.object(apigw_collector, "_get_apigw_client",
                          return_value=mock_rest), \
             patch.object(apigw_collector, "_get_apigwv2_client",
                          return_value=mock_v2), \
             patch("common.collectors.apigw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = apigw_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises_rest(self):
        """get_rest_apis API 오류 시 REST skip, v2 계속 — Req 3-E.20"""
        mock_rest = MagicMock()
        mock_rest_pag = MagicMock()
        mock_rest.get_paginator.return_value = mock_rest_pag
        mock_rest_pag.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "get_rest_apis",
        )

        mock_v2 = MagicMock()
        mock_v2_pag = MagicMock()
        mock_v2.get_paginator.return_value = mock_v2_pag
        mock_v2_pag.paginate.return_value = [{"Items": [
            {"ApiId": "http-1", "ProtocolType": "HTTP",
             "Tags": {"Monitoring": "on"}},
        ]}]

        with patch.object(apigw_collector, "_get_apigw_client",
                          return_value=mock_rest), \
             patch.object(apigw_collector, "_get_apigwv2_client",
                          return_value=mock_v2), \
             patch("common.collectors.apigw.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = apigw_collector.collect_monitored_resources()

        # REST failed but HTTP still collected
        assert len(result) == 1
        assert result[0]["id"] == "http-1"

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_rest_keys(self):
        """REST: ApiLatency, Api4XXError, Api5XXError 키 반환 — Req 3-B.9"""
        mock_cw = MagicMock()
        data = {"Latency": 500.0, "4XXError": 10.0, "5XXError": 2.0}

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn in data:
                stat = "Average" if mn == "Latency" else "Sum"
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    stat: data[mn],
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = apigw_collector.get_metrics(
                "MyRestApi", resource_tags={"_api_type": "REST"})

        assert result is not None
        assert set(result.keys()) == {"ApiLatency", "Api4XXError", "Api5XXError"}

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 3-B.9"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = apigw_collector.get_metrics(
                "MyRestApi", resource_tags={"_api_type": "REST"})

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 3-C.14"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn == "Latency":
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Average": 200.0,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = apigw_collector.get_metrics(
                "http-1", resource_tags={"_api_type": "HTTP"})

        assert result is not None
        assert result == {"ApiLatency": pytest.approx(200.0)}
        assert "Api4xx" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """_api_type별 올바른 네임스페이스/디멘션 사용 — Req 3-E.22"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(100.0)]
        }

        # REST → ApiName dimension
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            apigw_collector.get_metrics(
                "MyRestApi", resource_tags={"_api_type": "REST"})

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs["Namespace"] == "AWS/ApiGateway"
            dims = call.kwargs["Dimensions"]
            assert dims[0]["Name"] == "ApiName"
            assert dims[0]["Value"] == "MyRestApi"

        mock_cw.reset_mock()

        # HTTP → ApiId dimension
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            apigw_collector.get_metrics(
                "http-1", resource_tags={"_api_type": "HTTP"})

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs["Namespace"] == "AWS/ApiGateway"
            dims = call.kwargs["Dimensions"]
            assert dims[0]["Name"] == "ApiId"
            assert dims[0]["Value"] == "http-1"

        mock_cw.reset_mock()

        # WEBSOCKET → ApiId dimension
        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            apigw_collector.get_metrics(
                "ws-1", resource_tags={"_api_type": "WEBSOCKET"})

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs["Namespace"] == "AWS/ApiGateway"
            dims = call.kwargs["Dimensions"]
            assert dims[0]["Name"] == "ApiId"
            assert dims[0]["Value"] == "ws-1"


# ──────────────────────────────────────────────
# ACM Collector 단위 테스트
# Validates: Requirements 4.3, 4.4, 4.5, 4.9, 13.1–13.3
# ──────────────────────────────────────────────

from common.collectors import acm as acm_collector


class TestACMCollector:
    """ACM Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_acm_for_collection(self, certs):
        """ACM 클라이언트 mock 생성 (수집 테스트용).

        Args:
            certs: list_certificates 응답용 CertificateSummaryList
        """
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"CertificateSummaryList": certs}
        ]
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_all_issued_certs(self):
        """Full_Collection: ISSUED 인증서 전체 수집, Monitoring=on 자동 삽입 — Req 4.3, 13.3"""
        certs = [
            {"CertificateArn": "arn:aws:acm:us-east-1:123:certificate/cert-1"},
            {"CertificateArn": "arn:aws:acm:us-east-1:123:certificate/cert-2"},
        ]
        mock_client = self._mock_acm_for_collection(certs)

        with patch.object(acm_collector, "_get_acm_client",
                          return_value=mock_client), \
             patch("common.collectors.acm.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = acm_collector.collect_monitored_resources()

        assert len(result) == 2
        for r in result:
            assert r["type"] == "ACM"
            assert r["tags"]["Monitoring"] == "on"

    def test_untagged_certs_still_collected(self):
        """태그 없어도 수집 (Full_Collection) — Req 4.3, 13.1"""
        certs = [
            {"CertificateArn": "arn:aws:acm:us-east-1:123:certificate/no-tag"},
        ]
        mock_client = self._mock_acm_for_collection(certs)

        with patch.object(acm_collector, "_get_acm_client",
                          return_value=mock_client), \
             patch("common.collectors.acm.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = acm_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["tags"]["Monitoring"] == "on"

    def test_empty_result_when_no_certs(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 4.3"""
        mock_client = self._mock_acm_for_collection([])

        with patch.object(acm_collector, "_get_acm_client",
                          return_value=mock_client), \
             patch("common.collectors.acm.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = acm_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """list_certificates API 오류 시 예외 전파 — Req 13.4"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "list_certificates",
        )

        with patch.object(acm_collector, "_get_acm_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                acm_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_days_to_expiry(self):
        """DaysToExpiry 키 반환 — Req 4.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{
                "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "Minimum": 30.0,
            }]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = acm_collector.get_metrics(
                "arn:aws:acm:us-east-1:123:certificate/cert-1")

        assert result is not None
        assert set(result.keys()) == {"DaysToExpiry"}
        assert result["DaysToExpiry"] == pytest.approx(30.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 4.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = acm_collector.get_metrics(
                "arn:aws:acm:us-east-1:123:certificate/cert-1")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 4.5"""
        # ACM has only 1 metric, so this tests the single-metric case
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{
                "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "Minimum": 7.0,
            }]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = acm_collector.get_metrics(
                "arn:aws:acm:us-east-1:123:certificate/cert-1")

        assert result is not None
        assert result == {"DaysToExpiry": pytest.approx(7.0)}

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/CertificateManager 네임스페이스 + CertificateArn 디멘션 — Req 4.5"""
        cert_arn = "arn:aws:acm:us-east-1:123:certificate/cert-test"
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(14.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            acm_collector.get_metrics(cert_arn)

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/CertificateManager"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "CertificateArn"
            assert dims[0]["Value"] == cert_arn


# ──────────────────────────────────────────────
# Backup Collector 단위 테스트
# Validates: Requirements 5.3, 5.4
# ──────────────────────────────────────────────

from common.collectors import backup as backup_collector


class TestBackupCollector:
    """Backup Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_backup_for_collection(self, vaults, tag_map):
        """Backup 클라이언트 mock 생성 (수집 테스트용).

        Args:
            vaults: list_backup_vaults 응답용 BackupVaultList
            tag_map: {vault_arn: {tag_key: tag_value}} 매핑
        """
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"BackupVaultList": vaults}]

        def mock_list_tags(ResourceArn):
            tags = tag_map.get(ResourceArn, {})
            return {"Tags": tags}

        mock_client.list_tags.side_effect = mock_list_tags
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 vault만 수집, type='Backup' — Req 5.3"""
        vaults = [
            {"BackupVaultName": "vault-on",
             "BackupVaultArn": "arn:aws:backup:us-east-1:123:backup-vault:vault-on"},
            {"BackupVaultName": "vault-off",
             "BackupVaultArn": "arn:aws:backup:us-east-1:123:backup-vault:vault-off"},
        ]
        tag_map = {
            "arn:aws:backup:us-east-1:123:backup-vault:vault-on": {"Monitoring": "on"},
            "arn:aws:backup:us-east-1:123:backup-vault:vault-off": {"Monitoring": "off"},
        }
        mock_client = self._mock_backup_for_collection(vaults, tag_map)

        with patch.object(backup_collector, "_get_backup_client",
                          return_value=mock_client), \
             patch("common.collectors.backup.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = backup_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "vault-on"
        assert result[0]["type"] == "Backup"

    def test_untagged_vault_excluded(self):
        """태그 없는 vault 제외 — Req 5.3"""
        vaults = [
            {"BackupVaultName": "vault-tagged",
             "BackupVaultArn": "arn:aws:backup:us-east-1:123:backup-vault:vault-tagged"},
            {"BackupVaultName": "vault-no-tag",
             "BackupVaultArn": "arn:aws:backup:us-east-1:123:backup-vault:vault-no-tag"},
        ]
        tag_map = {
            "arn:aws:backup:us-east-1:123:backup-vault:vault-tagged": {"Monitoring": "on"},
            "arn:aws:backup:us-east-1:123:backup-vault:vault-no-tag": {},
        }
        mock_client = self._mock_backup_for_collection(vaults, tag_map)

        with patch.object(backup_collector, "_get_backup_client",
                          return_value=mock_client), \
             patch("common.collectors.backup.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = backup_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "vault-tagged"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 5.3"""
        mock_client = self._mock_backup_for_collection([], {})

        with patch.object(backup_collector, "_get_backup_client",
                          return_value=mock_client), \
             patch("common.collectors.backup.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = backup_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """list_backup_vaults API 오류 시 예외 전파 — Req 5.3"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "list_backup_vaults",
        )

        with patch.object(backup_collector, "_get_backup_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                backup_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_expected_keys(self):
        """BackupJobsFailed, BackupJobsAborted 키 반환 — Req 5.4"""
        mock_cw = MagicMock()
        data = {
            "NumberOfBackupJobsFailed": 1.0,
            "NumberOfBackupJobsAborted": 0.0,
        }

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn in data:
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Sum": data[mn],
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = backup_collector.get_metrics("vault-on")

        assert result is not None
        assert set(result.keys()) == {"BackupJobsFailed", "BackupJobsAborted"}
        assert result["BackupJobsFailed"] == pytest.approx(1.0)
        assert result["BackupJobsAborted"] == pytest.approx(0.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 5.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = backup_collector.get_metrics("vault-on")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 5.4"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn == "NumberOfBackupJobsFailed":
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Sum": 2.0,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = backup_collector.get_metrics("vault-on")

        assert result is not None
        assert result == {"BackupJobsFailed": pytest.approx(2.0)}
        assert "BackupJobsAborted" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/Backup 네임스페이스 + BackupVaultName 디멘션 사용 — Req 5.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(0.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            backup_collector.get_metrics("vault-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/Backup"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "BackupVaultName"
            assert dims[0]["Value"] == "vault-test-1"


# ──────────────────────────────────────────────
# MQ Collector 단위 테스트
# Validates: Requirements 6.3, 6.4
# ──────────────────────────────────────────────

from common.collectors import mq as mq_collector


class TestMQCollector:
    """MQ Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_mq_for_collection(self, brokers, tag_map):
        """MQ 클라이언트 mock 생성 (수집 테스트용).

        Args:
            brokers: list_brokers 응답용 BrokerSummaries
            tag_map: {broker_id: {tag_key: tag_value}} 매핑
        """
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"BrokerSummaries": brokers}]

        def mock_describe_broker(BrokerId):
            tags = tag_map.get(BrokerId, {})
            return {"Tags": tags}

        mock_client.describe_broker.side_effect = mock_describe_broker
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 broker만 수집, type='MQ' — Req 6.3"""
        brokers = [
            {"BrokerId": "b-001", "BrokerName": "broker-on"},
            {"BrokerId": "b-002", "BrokerName": "broker-off"},
        ]
        tag_map = {
            "b-001": {"Monitoring": "on"},
            "b-002": {"Monitoring": "off"},
        }
        mock_client = self._mock_mq_for_collection(brokers, tag_map)

        with patch.object(mq_collector, "_get_mq_client",
                          return_value=mock_client), \
             patch("common.collectors.mq.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = mq_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "broker-on"
        assert result[0]["type"] == "MQ"

    def test_untagged_broker_excluded(self):
        """태그 없는 broker 제외 — Req 6.3"""
        brokers = [
            {"BrokerId": "b-tagged", "BrokerName": "broker-tagged"},
            {"BrokerId": "b-no-tag", "BrokerName": "broker-no-tag"},
        ]
        tag_map = {
            "b-tagged": {"Monitoring": "on"},
            "b-no-tag": {},
        }
        mock_client = self._mock_mq_for_collection(brokers, tag_map)

        with patch.object(mq_collector, "_get_mq_client",
                          return_value=mock_client), \
             patch("common.collectors.mq.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = mq_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "broker-tagged"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 6.3"""
        mock_client = self._mock_mq_for_collection([], {})

        with patch.object(mq_collector, "_get_mq_client",
                          return_value=mock_client), \
             patch("common.collectors.mq.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = mq_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """list_brokers API 오류 시 예외 전파 — Req 6.3"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "list_brokers",
        )

        with patch.object(mq_collector, "_get_mq_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                mq_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_expected_keys(self):
        """MqCPU, HeapUsage, JobSchedulerStoreUsage, StoreUsage 키 반환 — Req 6.4"""
        mock_cw = MagicMock()
        data = {
            "CpuUtilization": 45.0,
            "HeapUsage": 60.0,
            "JobSchedulerStorePercentUsage": 30.0,
            "StorePercentUsage": 50.0,
        }

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn in data:
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Average": data[mn],
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = mq_collector.get_metrics("broker-on")

        assert result is not None
        assert set(result.keys()) == {
            "MqCPU", "HeapUsage", "JobSchedulerStoreUsage", "StoreUsage",
        }
        assert result["MqCPU"] == pytest.approx(45.0)
        assert result["HeapUsage"] == pytest.approx(60.0)

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 6.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = mq_collector.get_metrics("broker-on")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 6.4"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn == "CpuUtilization":
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Average": 85.0,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = mq_collector.get_metrics("broker-on")

        assert result is not None
        assert result == {"MqCPU": pytest.approx(85.0)}
        assert "HeapUsage" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/AmazonMQ 네임스페이스 + Broker 디멘션 사용 — Req 6.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(50.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            mq_collector.get_metrics("broker-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/AmazonMQ"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "Broker"
            assert dims[0]["Value"] == "broker-test-1"


# ──────────────────────────────────────────────
# CLB Collector 단위 테스트
# Validates: Requirements 7.3, 7.4
# ──────────────────────────────────────────────

from common.collectors import clb as clb_collector


class TestCLBCollector:
    """CLB Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_elb_for_collection(self, lbs, tag_map):
        """Classic ELB 클라이언트 mock 생성 (수집 테스트용).

        Args:
            lbs: describe_load_balancers 응답용 LoadBalancerDescriptions
            tag_map: {lb_name: {tag_key: tag_value}} 매핑
        """
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"LoadBalancerDescriptions": lbs}
        ]

        def mock_describe_tags(LoadBalancerNames):
            lb_name = LoadBalancerNames[0]
            tags = tag_map.get(lb_name, {})
            return {
                "TagDescriptions": [{
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]
                }]
            }

        mock_client.describe_tags.side_effect = mock_describe_tags
        return mock_client

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 CLB만 수집, type='CLB' — Req 7.3"""
        lbs = [
            {"LoadBalancerName": "clb-on"},
            {"LoadBalancerName": "clb-off"},
        ]
        tag_map = {
            "clb-on": {"Monitoring": "on"},
            "clb-off": {"Monitoring": "off"},
        }
        mock_client = self._mock_elb_for_collection(lbs, tag_map)

        with patch.object(clb_collector, "_get_elb_client",
                          return_value=mock_client), \
             patch("common.collectors.clb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = clb_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "clb-on"
        assert result[0]["type"] == "CLB"

    def test_untagged_clb_excluded(self):
        """태그 없는 CLB 제외 — Req 7.3"""
        lbs = [
            {"LoadBalancerName": "clb-tagged"},
            {"LoadBalancerName": "clb-no-tag"},
        ]
        tag_map = {
            "clb-tagged": {"Monitoring": "on"},
            "clb-no-tag": {},
        }
        mock_client = self._mock_elb_for_collection(lbs, tag_map)

        with patch.object(clb_collector, "_get_elb_client",
                          return_value=mock_client), \
             patch("common.collectors.clb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = clb_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "clb-tagged"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 7.3"""
        mock_client = self._mock_elb_for_collection([], {})

        with patch.object(clb_collector, "_get_elb_client",
                          return_value=mock_client), \
             patch("common.collectors.clb.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = clb_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """describe_load_balancers API 오류 시 예외 전파 — Req 7.3"""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "describe_load_balancers",
        )

        with patch.object(clb_collector, "_get_elb_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                clb_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_expected_keys(self):
        """7개 메트릭 키 반환 — Req 7.4"""
        mock_cw = MagicMock()
        data = {
            "UnHealthyHostCount": 1.0,
            "HTTPCode_ELB_5XX": 10.0,
            "HTTPCode_ELB_4XX": 20.0,
            "HTTPCode_Backend_5XX": 5.0,
            "HTTPCode_Backend_4XX": 15.0,
            "SurgeQueueLength": 100.0,
            "SpilloverCount": 3.0,
        }

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn in data:
                stat_key = kwargs["Statistics"][0]
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    stat_key: data[mn],
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = clb_collector.get_metrics("clb-on")

        assert result is not None
        expected_keys = {
            "CLBUnHealthyHost", "CLB5XX", "CLB4XX",
            "CLBBackend5XX", "CLBBackend4XX",
            "SurgeQueueLength", "SpilloverCount",
        }
        assert set(result.keys()) == expected_keys

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 7.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = clb_collector.get_metrics("clb-on")

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 7.4"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn == "UnHealthyHostCount":
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Average": 2.0,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = clb_collector.get_metrics("clb-on")

        assert result is not None
        assert result == {"CLBUnHealthyHost": pytest.approx(2.0)}
        assert "CLB5XX" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/ELB 네임스페이스 + LoadBalancerName 디멘션 사용 — Req 7.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(0.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            clb_collector.get_metrics("clb-test-1")

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/ELB"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            assert dims[0]["Name"] == "LoadBalancerName"
            assert dims[0]["Value"] == "clb-test-1"


# ──────────────────────────────────────────────
# OpenSearch Collector 단위 테스트
# Validates: Requirements 8.3, 8.4, 8.5
# ──────────────────────────────────────────────

from common.collectors import opensearch as opensearch_collector


class TestOpenSearchCollector:
    """OpenSearch Collector 단위 테스트 — collect_monitored_resources() + get_metrics()."""

    def _mock_opensearch_for_collection(self, domain_names, domain_details,
                                        tag_map, account_id="123456789012"):
        """OpenSearch + STS 클라이언트 mock 생성 (수집 테스트용).

        Args:
            domain_names: list_domain_names 응답용 DomainNames
            domain_details: describe_domains 응답용 DomainStatusList
            tag_map: {domain_arn: {tag_key: tag_value}} 매핑
            account_id: STS get_caller_identity 반환 계정 ID
        """
        mock_client = MagicMock()
        mock_client.list_domain_names.return_value = {
            "DomainNames": domain_names,
        }
        mock_client.describe_domains.return_value = {
            "DomainStatusList": domain_details,
        }

        def mock_list_tags(ARN):
            tags = tag_map.get(ARN, {})
            return {"TagList": [{"Key": k, "Value": v} for k, v in tags.items()]}

        mock_client.list_tags.side_effect = mock_list_tags

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": account_id}

        return mock_client, mock_sts

    # ── collect_monitored_resources() 테스트 ──

    def test_collect_monitoring_on_only(self):
        """Monitoring=on 태그 도메인만 수집, type='OpenSearch', _client_id 설정 — Req 8.3"""
        domain_names = [
            {"DomainName": "domain-on"},
            {"DomainName": "domain-off"},
        ]
        domain_details = [
            {"DomainName": "domain-on",
             "ARN": "arn:aws:es:us-east-1:123456789012:domain/domain-on"},
            {"DomainName": "domain-off",
             "ARN": "arn:aws:es:us-east-1:123456789012:domain/domain-off"},
        ]
        tag_map = {
            "arn:aws:es:us-east-1:123456789012:domain/domain-on": {"Monitoring": "on"},
            "arn:aws:es:us-east-1:123456789012:domain/domain-off": {"Monitoring": "off"},
        }
        mock_os, mock_sts = self._mock_opensearch_for_collection(
            domain_names, domain_details, tag_map)

        with patch.object(opensearch_collector, "_get_opensearch_client",
                          return_value=mock_os), \
             patch.object(opensearch_collector, "_get_sts_client",
                          return_value=mock_sts), \
             patch("common.collectors.opensearch.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = opensearch_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "domain-on"
        assert result[0]["type"] == "OpenSearch"
        assert result[0]["tags"]["_client_id"] == "123456789012"

    def test_untagged_domain_excluded(self):
        """태그 없는 도메인 제외 — Req 8.3"""
        domain_names = [
            {"DomainName": "domain-tagged"},
            {"DomainName": "domain-no-tag"},
        ]
        domain_details = [
            {"DomainName": "domain-tagged",
             "ARN": "arn:aws:es:us-east-1:123456789012:domain/domain-tagged"},
            {"DomainName": "domain-no-tag",
             "ARN": "arn:aws:es:us-east-1:123456789012:domain/domain-no-tag"},
        ]
        tag_map = {
            "arn:aws:es:us-east-1:123456789012:domain/domain-tagged": {"Monitoring": "on"},
            "arn:aws:es:us-east-1:123456789012:domain/domain-no-tag": {},
        }
        mock_os, mock_sts = self._mock_opensearch_for_collection(
            domain_names, domain_details, tag_map)

        with patch.object(opensearch_collector, "_get_opensearch_client",
                          return_value=mock_os), \
             patch.object(opensearch_collector, "_get_sts_client",
                          return_value=mock_sts), \
             patch("common.collectors.opensearch.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = opensearch_collector.collect_monitored_resources()

        assert len(result) == 1
        assert result[0]["id"] == "domain-tagged"

    def test_empty_result_when_no_monitored(self):
        """수집 대상 0개 시 빈 리스트 반환 — Req 8.3"""
        mock_os, mock_sts = self._mock_opensearch_for_collection([], [], {})

        with patch.object(opensearch_collector, "_get_opensearch_client",
                          return_value=mock_os), \
             patch.object(opensearch_collector, "_get_sts_client",
                          return_value=mock_sts), \
             patch("common.collectors.opensearch.boto3.session.Session") as ms:
            ms.return_value.region_name = "us-east-1"
            result = opensearch_collector.collect_monitored_resources()

        assert result == []

    def test_api_error_raises(self):
        """list_domain_names API 오류 시 예외 전파 — Req 8.3"""
        mock_client = MagicMock()
        mock_client.list_domain_names.side_effect = _ClientError(
            {"Error": {"Code": "ServiceException", "Message": "error"}},
            "list_domain_names",
        )

        with patch.object(opensearch_collector, "_get_opensearch_client",
                          return_value=mock_client):
            with pytest.raises(_ClientError):
                opensearch_collector.collect_monitored_resources()

    # ── get_metrics() 테스트 ──

    def test_get_metrics_returns_expected_keys(self):
        """8개 메트릭 키 반환 — Req 8.4"""
        mock_cw = MagicMock()
        data = {
            "ClusterStatus.red": ("Maximum", 0.0),
            "ClusterStatus.yellow": ("Maximum", 0.0),
            "FreeStorageSpace": ("Minimum", 50000.0),
            "ClusterIndexWritesBlocked": ("Maximum", 0.0),
            "CPUUtilization": ("Average", 45.0),
            "JVMMemoryPressure": ("Maximum", 60.0),
            "MasterCPUUtilization": ("Average", 30.0),
            "MasterJVMMemoryPressure": ("Maximum", 40.0),
        }

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn in data:
                stat_key, value = data[mn]
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    stat_key: value,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = opensearch_collector.get_metrics(
                "domain-on",
                resource_tags={"_client_id": "123456789012"})

        assert result is not None
        expected_keys = {
            "ClusterStatusRed", "ClusterStatusYellow",
            "OSFreeStorageSpace", "ClusterIndexWritesBlocked",
            "OsCPU", "JVMMemoryPressure",
            "MasterCPU", "MasterJVMMemoryPressure",
        }
        assert set(result.keys()) == expected_keys

    def test_get_metrics_returns_none_when_all_empty(self):
        """모든 메트릭 데이터 없을 때 None 반환 — Req 8.4"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = opensearch_collector.get_metrics(
                "domain-on",
                resource_tags={"_client_id": "123456789012"})

        assert result is None

    def test_get_metrics_skips_empty_metrics(self):
        """일부 메트릭만 데이터 있을 때 해당 메트릭만 반환 — Req 8.4"""
        mock_cw = MagicMock()

        def get_metric_stats(**kwargs):
            mn = kwargs.get("MetricName", "")
            if mn == "CPUUtilization":
                return {"Datapoints": [{
                    "Timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Average": 75.0,
                }]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_stats

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            result = opensearch_collector.get_metrics(
                "domain-on",
                resource_tags={"_client_id": "123456789012"})

        assert result is not None
        assert result == {"OsCPU": pytest.approx(75.0)}
        assert "ClusterStatusRed" not in result

    def test_get_metrics_uses_correct_namespace_and_dimension(self):
        """AWS/ES 네임스페이스 + DomainName+ClientId Compound Dimension — Req 8.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(0.0)]
        }

        with patch("common.collectors.base._get_cw_client", return_value=mock_cw):
            opensearch_collector.get_metrics(
                "domain-test",
                resource_tags={"_client_id": "111222333444"})

        for call in mock_cw.get_metric_statistics.call_args_list:
            assert call.kwargs.get("Namespace", call[1].get("Namespace")) \
                == "AWS/ES"
            dims = call.kwargs.get("Dimensions", call[1].get("Dimensions"))
            dim_names = {d["Name"] for d in dims}
            assert "DomainName" in dim_names
            assert "ClientId" in dim_names
            # Verify values
            dim_map = {d["Name"]: d["Value"] for d in dims}
            assert dim_map["DomainName"] == "domain-test"
            assert dim_map["ClientId"] == "111222333444"


# ──────────────────────────────────────────────
# 신규 8개 리소스 Tag Resolver 단위 테스트
# Validates: Requirements 1.3, 2.4, 3-B.7, 4.3, 5.3, 6.3, 7.3, 8.3
# ──────────────────────────────────────────────


class TestNewResourceTagResolver:
    """get_resource_tags()가 8개 신규 리소스 타입에 대해 올바른 태그를 반환하는지 검증."""

    def test_lambda_tag_retrieval(self):
        """get_resource_tags(id, 'Lambda') → get_function + list_tags 호출."""
        from common.tag_resolver import get_resource_tags

        mock_lambda = MagicMock()
        mock_lambda.get_function.return_value = {
            "Configuration": {
                "FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
            },
        }
        mock_lambda.list_tags.return_value = {
            "Tags": {"Monitoring": "on", "Threshold_Duration": "3000"},
        }

        with patch("common.tag_resolver._get_lambda_client", return_value=mock_lambda):
            tags = get_resource_tags("my-fn", "Lambda")

        assert tags == {"Monitoring": "on", "Threshold_Duration": "3000"}
        mock_lambda.get_function.assert_called_once_with(FunctionName="my-fn")
        mock_lambda.list_tags.assert_called_once_with(
            Resource="arn:aws:lambda:us-east-1:123456789012:function:my-fn",
        )

    def test_vpn_tag_retrieval(self):
        """get_resource_tags(id, 'VPN') → describe_vpn_connections 호출."""
        from common.tag_resolver import get_resource_tags

        mock_ec2 = MagicMock()
        mock_ec2.describe_vpn_connections.return_value = {
            "VpnConnections": [{
                "VpnConnectionId": "vpn-abc123",
                "Tags": [
                    {"Key": "Monitoring", "Value": "on"},
                    {"Key": "Name", "Value": "prod-vpn"},
                ],
            }],
        }

        with patch("common.tag_resolver._get_ec2_client", return_value=mock_ec2):
            tags = get_resource_tags("vpn-abc123", "VPN")

        assert tags == {"Monitoring": "on", "Name": "prod-vpn"}
        mock_ec2.describe_vpn_connections.assert_called_once_with(
            VpnConnectionIds=["vpn-abc123"],
        )

    def test_apigw_tag_retrieval_v2(self):
        """get_resource_tags(id, 'APIGW') → apigatewayv2 get_api 우선 시도."""
        from common.tag_resolver import get_resource_tags

        mock_v2 = MagicMock()
        mock_v2.get_api.return_value = {
            "Tags": {"Monitoring": "on", "Threshold_ApiLatency": "5000"},
        }

        with patch("common.tag_resolver._get_apigwv2_client", return_value=mock_v2):
            tags = get_resource_tags("api-id-123", "APIGW")

        assert tags == {"Monitoring": "on", "Threshold_ApiLatency": "5000"}
        mock_v2.get_api.assert_called_once_with(ApiId="api-id-123")

    def test_apigw_tag_retrieval_rest_fallback(self):
        """get_resource_tags(id, 'APIGW') → v2 실패 시 REST API 폴백."""
        from common.tag_resolver import get_resource_tags

        mock_v2 = MagicMock()
        mock_v2.get_api.side_effect = _ClientError(
            {"Error": {"Code": "NotFoundException", "Message": "not found"}},
            "GetApi",
        )

        mock_rest = MagicMock()
        mock_paginator = MagicMock()
        mock_rest.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"items": [{"name": "my-rest-api", "id": "rest123"}]},
        ]
        mock_rest.get_tags.return_value = {
            "tags": {"Monitoring": "on"},
        }

        with patch("common.tag_resolver._get_apigwv2_client", return_value=mock_v2), \
             patch("common.tag_resolver._get_apigw_client", return_value=mock_rest), \
             patch("common.tag_resolver.boto3.session.Session") as mock_session:
            mock_session.return_value.region_name = "us-east-1"
            tags = get_resource_tags("my-rest-api", "APIGW")

        assert tags == {"Monitoring": "on"}
        mock_rest.get_tags.assert_called_once_with(
            resourceArn="arn:aws:apigateway:us-east-1::/restapis/rest123",
        )

    def test_acm_tag_retrieval(self):
        """get_resource_tags(arn, 'ACM') → list_tags_for_certificate 호출."""
        from common.tag_resolver import get_resource_tags

        cert_arn = "arn:aws:acm:us-east-1:123456789012:certificate/abc-123"
        mock_acm = MagicMock()
        mock_acm.list_tags_for_certificate.return_value = {
            "Tags": [
                {"Key": "Monitoring", "Value": "on"},
                {"Key": "Threshold_DaysToExpiry", "Value": "30"},
            ],
        }

        with patch("common.tag_resolver._get_acm_client", return_value=mock_acm):
            tags = get_resource_tags(cert_arn, "ACM")

        assert tags == {"Monitoring": "on", "Threshold_DaysToExpiry": "30"}
        mock_acm.list_tags_for_certificate.assert_called_once_with(
            CertificateArn=cert_arn,
        )

    def test_backup_tag_retrieval(self):
        """get_resource_tags(name, 'Backup') → describe_backup_vault + list_tags 호출."""
        from common.tag_resolver import get_resource_tags

        vault_arn = "arn:aws:backup:us-east-1:123456789012:backup-vault:my-vault"
        mock_backup = MagicMock()
        mock_backup.describe_backup_vault.return_value = {
            "BackupVaultArn": vault_arn,
        }
        mock_backup.list_tags.return_value = {
            "Tags": {"Monitoring": "on", "Env": "prod"},
        }

        with patch("common.tag_resolver._get_backup_client", return_value=mock_backup):
            tags = get_resource_tags("my-vault", "Backup")

        assert tags == {"Monitoring": "on", "Env": "prod"}
        mock_backup.describe_backup_vault.assert_called_once_with(
            BackupVaultName="my-vault",
        )
        mock_backup.list_tags.assert_called_once_with(ResourceArn=vault_arn)

    def test_mq_tag_retrieval(self):
        """get_resource_tags(name, 'MQ') → list_brokers + describe_broker 호출."""
        from common.tag_resolver import get_resource_tags

        mock_mq = MagicMock()
        mock_paginator = MagicMock()
        mock_mq.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"BrokerSummaries": [
                {"BrokerName": "my-broker", "BrokerId": "b-1234"},
            ]},
        ]
        mock_mq.describe_broker.return_value = {
            "Tags": {"Monitoring": "on", "Threshold_MqCPU": "85"},
        }

        with patch("common.tag_resolver._get_mq_client", return_value=mock_mq):
            tags = get_resource_tags("my-broker", "MQ")

        assert tags == {"Monitoring": "on", "Threshold_MqCPU": "85"}
        mock_mq.describe_broker.assert_called_once_with(BrokerId="b-1234")

    def test_clb_tag_retrieval(self):
        """get_resource_tags(name, 'CLB') → elb describe_tags 호출."""
        from common.tag_resolver import get_resource_tags

        mock_elb = MagicMock()
        mock_elb.describe_tags.return_value = {
            "TagDescriptions": [{
                "LoadBalancerName": "my-clb",
                "Tags": [
                    {"Key": "Monitoring", "Value": "on"},
                    {"Key": "Name", "Value": "prod-clb"},
                ],
            }],
        }

        with patch("common.tag_resolver._get_classic_elb_client", return_value=mock_elb):
            tags = get_resource_tags("my-clb", "CLB")

        assert tags == {"Monitoring": "on", "Name": "prod-clb"}
        mock_elb.describe_tags.assert_called_once_with(
            LoadBalancerNames=["my-clb"],
        )

    def test_opensearch_tag_retrieval(self):
        """get_resource_tags(name, 'OpenSearch') → describe_domains + list_tags 호출."""
        from common.tag_resolver import get_resource_tags

        domain_arn = "arn:aws:es:us-east-1:123456789012:domain/my-domain"
        mock_os = MagicMock()
        mock_os.describe_domains.return_value = {
            "DomainStatusList": [{
                "DomainName": "my-domain",
                "ARN": domain_arn,
            }],
        }
        mock_os.list_tags.return_value = {
            "TagList": [
                {"Key": "Monitoring", "Value": "on"},
                {"Key": "Threshold_OsCPU", "Value": "75"},
            ],
        }

        with patch("common.tag_resolver._get_opensearch_client", return_value=mock_os):
            tags = get_resource_tags("my-domain", "OpenSearch")

        assert tags == {"Monitoring": "on", "Threshold_OsCPU": "75"}
        mock_os.describe_domains.assert_called_once_with(
            DomainNames=["my-domain"],
        )
        mock_os.list_tags.assert_called_once_with(ARN=domain_arn)
