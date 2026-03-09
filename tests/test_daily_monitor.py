"""
Daily_Monitor 테스트 - Property 6, 8 속성 테스트 + 단위 테스트

Requirements: 1.1, 1.3, 1.4, 3.1, 3.3, 3.4, 3.5, 6.3, 6.4
"""

import json
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from daily_monitor.lambda_handler import lambda_handler as handler


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _make_resource(resource_id, resource_type="EC2", tags=None):
    return {
        "id": resource_id,
        "type": resource_type,
        "tags": tags or {"Monitoring": "on"},
        "region": "us-east-1",
    }


def _patch_all_collectors(ec2_resources=None, rds_resources=None, elb_resources=None):
    """세 collector 모두 패치하는 컨텍스트 매니저 반환."""
    return (
        patch("daily_monitor.lambda_handler.ec2_collector.collect_monitored_resources",
              return_value=ec2_resources or []),
        patch("daily_monitor.lambda_handler.rds_collector.collect_monitored_resources",
              return_value=rds_resources or []),
        patch("daily_monitor.lambda_handler.elb_collector.collect_monitored_resources",
              return_value=elb_resources or []),
    )# ──────────────────────────────────────────────
# Property 6: InsufficientData 메트릭 알림 건너뛰기
# Validates: Requirements 3.5
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    resource_ids=st.lists(
        st.text(min_size=2, max_size=15,
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                       whitelist_characters="-")),
        min_size=1, max_size=5, unique=True,
    )
)
def test_property_6_insufficient_data_no_alert(resource_ids):
    """Feature: aws-monitoring-engine, Property 6: InsufficientData 메트릭 알림 건너뛰기"""
    resources = [_make_resource(rid) for rid in resource_ids]

    p1, p2, p3 = _patch_all_collectors(ec2_resources=resources)
    with p1, p2, p3, \
         patch("common.collectors.ec2.get_metrics", return_value=None), \
         patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
        result = handler({}, MagicMock())

    # 메트릭 데이터 없으면 알림 0건
    mock_alert.assert_not_called()
    assert result["alerts"] == 0
    assert result["processed"] == len(resource_ids)


# ──────────────────────────────────────────────
# Property 8: 복수 리소스 개별 알림 발송
# Validates: Requirements 3.3
# ──────────────────────────────────────────────

@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    cpu_values=st.lists(
        st.floats(min_value=81.0, max_value=100.0, allow_nan=False),
        min_size=1, max_size=5,
    )
)
def test_property_8_multiple_resources_individual_alerts(cpu_values):
    """Feature: aws-monitoring-engine, Property 8: 복수 리소스 개별 알림 발송"""
    resources = [_make_resource(f"i-{i:03d}") for i in range(len(cpu_values))]
    # 각 리소스마다 CPU 임계치 초과 메트릭 반환
    metrics_list = [{"CPU": v} for v in cpu_values]

    p1, p2, p3 = _patch_all_collectors(ec2_resources=resources)
    with p1, p2, p3, \
         patch("common.collectors.ec2.get_metrics", side_effect=metrics_list), \
         patch("daily_monitor.lambda_handler.send_alert") as mock_alert, \
         patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0):
        result = handler({}, MagicMock())

    # N개 리소스 → N개 알림
    assert mock_alert.call_count == len(cpu_values)
    assert result["alerts"] == len(cpu_values)


# ──────────────────────────────────────────────
# 단위 테스트
# ──────────────────────────────────────────────

class TestDailyMonitorHandler:

    def test_no_resources_no_alert(self):
        """수집 대상 0개 시 알림 미발송 - Requirements 1.3"""
        p1, p2, p3 = _patch_all_collectors()
        with p1, p2, p3, \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()
        assert result["processed"] == 0
        assert result["alerts"] == 0

    def test_threshold_exceeded_sends_alert(self):
        """임계치 초과 시 SNS 알림 발송 - Requirements 3.1"""
        resources = [_make_resource("i-001")]
        p1, p2, p3 = _patch_all_collectors(ec2_resources=resources)
        with p1, p2, p3, \
             patch("common.collectors.ec2.get_metrics",
                   return_value={"CPU": 95.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_called_once_with(
            resource_id="i-001",
            resource_type="EC2",
            metric_name="CPU",
            current_value=95.0,
            threshold=80.0,
        )
        assert result["alerts"] == 1

    def test_threshold_not_exceeded_no_alert(self):
        """임계치 미초과 시 알림 미발송"""
        resources = [_make_resource("i-001")]
        p1, p2, p3 = _patch_all_collectors(ec2_resources=resources)
        with p1, p2, p3, \
             patch("common.collectors.ec2.get_metrics",
                   return_value={"CPU": 50.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()
        assert result["alerts"] == 0

    def test_collector_error_sends_error_alert_and_continues(self):
        """Collector 오류 시 SNS 오류 알림 발송 후 다음 collector 계속 - Requirements 1.4"""
        rds_resources = [_make_resource("db-001", "RDS")]

        with patch("daily_monitor.lambda_handler.ec2_collector.collect_monitored_resources",
                   side_effect=Exception("EC2 API error")), \
             patch("daily_monitor.lambda_handler.rds_collector.collect_monitored_resources",
                   return_value=rds_resources), \
             patch("daily_monitor.lambda_handler.elb_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("common.collectors.rds.get_metrics",
                   return_value={"CPU": 50.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_error_alert") as mock_err, \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        # EC2 오류 알림 1건만 발송
        mock_err.assert_called_once()
        # RDS는 정상 처리
        assert result["processed"] == 1
        mock_alert.assert_not_called()  # CPU 50 < 80 이므로 알림 없음

    def test_single_resource_error_does_not_stop_others(self):
        """단일 리소스 오류가 다른 리소스 처리를 중단시키지 않음 - Requirements 6.4"""
        resources = [
            _make_resource("i-001"),
            _make_resource("i-002"),
        ]

        call_count = {"n": 0}

        def get_metrics_side_effect(resource_id, tags):
            call_count["n"] += 1
            if resource_id == "i-001":
                raise Exception("metric error")
            return {"CPU": 50.0}

        p1, p2, p3 = _patch_all_collectors(ec2_resources=resources)
        with p1, p2, p3, \
             patch("common.collectors.ec2.get_metrics",
                   side_effect=get_metrics_side_effect), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_error_alert") as mock_err, \
             patch("daily_monitor.lambda_handler.send_alert"):
            result = handler({}, MagicMock())

        # i-001 오류 알림 1건만 발송
        mock_err.assert_called_once()
        # i-002는 정상 처리
        assert result["processed"] == 1

    def test_free_memory_below_threshold_sends_alert(self):
        """FreeMemoryGB가 임계치 미만일 때 알림 발송 (낮을수록 위험)"""
        resources = [_make_resource("db-001", "RDS")]
        p1, p2, p3 = _patch_all_collectors(rds_resources=resources)
        with p1, p2, p3, \
             patch("common.collectors.rds.get_metrics",
                   return_value={"FreeMemoryGB": 1.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=2.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_called_once_with(
            resource_id="db-001",
            resource_type="RDS",
            metric_name="FreeMemoryGB",
            current_value=1.0,
            threshold=2.0,
        )
        assert result["alerts"] == 1

    def test_free_memory_above_threshold_no_alert(self):
        """FreeMemoryGB가 임계치 이상이면 알림 미발송"""
        resources = [_make_resource("db-001", "RDS")]
        p1, p2, p3 = _patch_all_collectors(rds_resources=resources)
        with p1, p2, p3, \
             patch("common.collectors.rds.get_metrics",
                   return_value={"FreeMemoryGB": 5.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=2.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()

    def test_returns_ok_status(self):
        """핸들러가 항상 status=ok 반환"""
        p1, p2, p3 = _patch_all_collectors()
        with p1, p2, p3:
            result = handler({}, MagicMock())

        assert result["status"] == "ok"
