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
