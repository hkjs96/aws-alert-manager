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


def _make_rds_instance(db_id: str, db_arn: str, status: str = "available") -> dict:
    return {
        "DBInstanceIdentifier": db_id,
        "DBInstanceArn": db_arn,
        "DBInstanceStatus": status,
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
        st.text(min_size=2, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
        min_size=0, max_size=5, unique=True,
    ),
    unmonitored_ids=st.lists(
        st.text(min_size=2, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
        min_size=0, max_size=5, unique=True,
    ),
)
def test_property_1_ec2_collection_filter(monitored_ids, unmonitored_ids):
    """Feature: aws-monitoring-engine, Property 1: EC2 수집 결과 필터링 정확성"""
    # ID 중복 제거
    unmonitored_ids = [i for i in unmonitored_ids if i not in monitored_ids]

    monitored = [_make_ec2_instance(i, {"Monitoring": "on"}) for i in monitored_ids]
    # unmonitored는 describe_instances 필터에 걸리지 않으므로 응답에 포함하지 않음
    # (실제 AWS는 Filters=[tag:Monitoring=on]으로 이미 필터링해서 반환)
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _make_ec2_response(monitored)

    with patch("common.collectors.ec2.boto3.client", return_value=mock_ec2), \
         patch("common.collectors.ec2.boto3.session.Session") as mock_session:
        mock_session.return_value.region_name = "us-east-1"
        from common.collectors.ec2 import collect_monitored_resources
        result = collect_monitored_resources()

    result_ids = {r["id"] for r in result}

    # Monitoring=on 태그 있는 것만 포함
    for mid in monitored_ids:
        assert mid in result_ids, f"{mid} should be in result"

    # unmonitored는 애초에 API 응답에 없으므로 결과에도 없어야 함
    for uid in unmonitored_ids:
        assert uid not in result_ids, f"{uid} should NOT be in result"


# ──────────────────────────────────────────────
# Property 5: 삭제된 리소스 수집 제외 (EC2)
# Validates: Requirements 1.5
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    active_ids=st.lists(
        st.text(min_size=2, max_size=15, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-")),
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

    with patch("common.collectors.ec2.boto3.client", return_value=mock_ec2), \
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
        with patch("common.collectors.ec2.boto3.client", return_value=mock_ec2), \
             patch("common.collectors.ec2.boto3.session.Session", mock_session):
            result = self.module.collect_monitored_resources()
        assert result == []

    def test_api_error_raises(self):
        """AWS API 오류 시 예외 전파 - Requirements 1.4"""
        from botocore.exceptions import ClientError
        mock_ec2 = MagicMock()
        mock_ec2.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "error"}}, "describe_instances"
        )
        with patch("common.collectors.ec2.boto3.client", return_value=mock_ec2):
            with pytest.raises(ClientError):
                self.module.collect_monitored_resources()

    def test_get_metrics_returns_cpu(self):
        """CPUUtilization 메트릭 정상 반환"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(75.0)]
        }
        with patch("common.collectors.ec2.boto3.client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {})
        assert result is not None
        assert result["CPU"] == pytest.approx(75.0)

    def test_get_metrics_returns_none_when_no_data(self):
        """CloudWatch 데이터 없을 때 None 반환 - Requirements 3.5"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        with patch("common.collectors.ec2.boto3.client", return_value=mock_cw):
            result = self.module.get_metrics("i-123", {})
        assert result is None

    def test_get_metrics_skips_memory_without_tag(self):
        """Threshold_Memory 태그 없으면 Memory 메트릭 조회 안 함"""
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [_make_cw_datapoint(60.0)]
        }
        with patch("common.collectors.ec2.boto3.client", return_value=mock_cw):
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
        with patch("common.collectors.ec2.boto3.client", return_value=mock_cw):
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
                _make_rds_instance("db-monitored", "arn:aws:rds:us-east-1:123:db:db-monitored"),
                _make_rds_instance("db-unmonitored", "arn:aws:rds:us-east-1:123:db:db-unmonitored"),
            ]
        }]

        def mock_list_tags(ResourceName):
            if "db-monitored" in ResourceName:
                return {"TagList": [{"Key": "Monitoring", "Value": "on"}]}
            return {"TagList": []}

        mock_rds.list_tags_for_resource.side_effect = mock_list_tags

        with patch("common.collectors.rds.boto3.client", return_value=mock_rds), \
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
        with patch("common.collectors.rds.boto3.client", return_value=mock_cw):
            result = get_metrics("db-123")

        assert result["FreeMemoryGB"] == pytest.approx(2.0)
        assert result["FreeStorageGB"] == pytest.approx(2.0)

    def test_get_metrics_returns_none_when_no_data(self):
        """CloudWatch 데이터 없을 때 None 반환"""
        from common.collectors.rds import get_metrics

        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        with patch("common.collectors.rds.boto3.client", return_value=mock_cw):
            result = get_metrics("db-123")
        assert result is None
