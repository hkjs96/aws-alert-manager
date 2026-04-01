"""
Daily_Monitor 테스트 - Property 6, 8 속성 테스트 + 단위 테스트

Requirements: 1.1, 1.3, 1.4, 3.1, 3.3, 3.4, 3.5, 6.3, 6.4
"""

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from daily_monitor.lambda_handler import (
    _classify_alarm,
    _cleanup_orphan_alarms,
    _process_resource,
    lambda_handler as handler,
)


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


def _patch_all_collectors(ec2_resources=None, rds_resources=None, elb_resources=None,
                         docdb_resources=None, elasticache_resources=None,
                         natgw_resources=None, lambda_resources=None,
                         vpn_resources=None, apigw_resources=None,
                         acm_resources=None, backup_resources=None,
                         mq_resources=None, clb_resources=None,
                         opensearch_resources=None):
    """모든 collector를 패치하는 ExitStack 컨텍스트 매니저 반환."""
    stack = ExitStack()
    collectors = [
        ("ec2_collector", ec2_resources),
        ("rds_collector", rds_resources),
        ("elb_collector", elb_resources),
        ("docdb_collector", docdb_resources),
        ("elasticache_collector", elasticache_resources),
        ("natgw_collector", natgw_resources),
        ("lambda_collector", lambda_resources),
        ("vpn_collector", vpn_resources),
        ("apigw_collector", apigw_resources),
        ("acm_collector", acm_resources),
        ("backup_collector", backup_resources),
        ("mq_collector", mq_resources),
        ("clb_collector", clb_resources),
        ("opensearch_collector", opensearch_resources),
    ]
    for name, resources in collectors:
        stack.enter_context(
            patch(f"daily_monitor.lambda_handler.{name}.collect_monitored_resources",
                  return_value=resources or [])
        )
    return stack


# ──────────────────────────────────────────────
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

    with _patch_all_collectors(ec2_resources=resources), \
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

    with _patch_all_collectors(ec2_resources=resources), \
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
        with _patch_all_collectors(), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()
        assert result["processed"] == 0
        assert result["alerts"] == 0

    def test_threshold_exceeded_sends_alert(self):
        """임계치 초과 시 SNS 알림 발송 - Requirements 3.1"""
        resources = [_make_resource("i-001")]
        with _patch_all_collectors(ec2_resources=resources), \
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
            tag_name="",
        )
        assert result["alerts"] == 1

    def test_threshold_not_exceeded_no_alert(self):
        """임계치 미초과 시 알림 미발송"""
        resources = [_make_resource("i-001")]
        with _patch_all_collectors(ec2_resources=resources), \
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
             patch("daily_monitor.lambda_handler.docdb_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.elasticache_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.natgw_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.lambda_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.vpn_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.apigw_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.acm_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.backup_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.mq_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.clb_collector.collect_monitored_resources",
                   return_value=[]), \
             patch("daily_monitor.lambda_handler.opensearch_collector.collect_monitored_resources",
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

        with _patch_all_collectors(ec2_resources=resources), \
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
        with _patch_all_collectors(rds_resources=resources), \
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
            tag_name="",
        )
        assert result["alerts"] == 1

    def test_free_memory_above_threshold_no_alert(self):
        """FreeMemoryGB가 임계치 이상이면 알림 미발송"""
        resources = [_make_resource("db-001", "RDS")]
        with _patch_all_collectors(rds_resources=resources), \
             patch("common.collectors.rds.get_metrics",
                   return_value={"FreeMemoryGB": 5.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=2.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()

    def test_returns_ok_status(self):
        """핸들러가 항상 status=ok 반환"""
        with _patch_all_collectors():
            result = handler({}, MagicMock())

        assert result["status"] == "ok"

    def test_alb_resource_threshold_exceeded_sends_alert(self):
        """ALB 리소스 임계치 초과 시 SNS 알림 발송"""
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        resources = [_make_resource(alb_arn, resource_type="ALB")]
        with _patch_all_collectors(elb_resources=resources), \
             patch("common.collectors.elb.get_metrics",
                   return_value={"RequestCount": 6000.0}), \
             patch("daily_monitor.lambda_handler.get_threshold", return_value=5000.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_called_once_with(
            resource_id=alb_arn,
            resource_type="ALB",
            metric_name="RequestCount",
            current_value=6000.0,
            threshold=5000.0,
            tag_name="",
        )
        assert result["alerts"] == 1

    def test_nlb_resource_no_metrics_skipped(self):
        """NLB 리소스 메트릭 없으면 알림 미발송"""
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        resources = [_make_resource(nlb_arn, resource_type="NLB")]
        with _patch_all_collectors(elb_resources=resources), \
             patch("common.collectors.elb.get_metrics", return_value=None), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            result = handler({}, MagicMock())

        mock_alert.assert_not_called()


# ──────────────────────────────────────────────
# 고아 알람 정리 테스트 (Task 4.5 확장)
# ──────────────────────────────────────────────

class TestClassifyAlarm:
    """_classify_alarm 단위 테스트 — 새 포맷/레거시 포맷 분류."""

    def test_new_format_ec2(self):
        result = {}
        _classify_alarm("[EC2] my-server CPUUtilization > 80% (TagName: i-001)", result)
        assert "EC2" in result
        assert "i-001" in result["EC2"]

    def test_new_format_rds(self):
        result = {}
        _classify_alarm("[RDS] my-db CPUUtilization > 80% (TagName: db-001)", result)
        assert "RDS" in result
        assert "db-001" in result["RDS"]

    def test_new_format_elb(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        result = {}
        _classify_alarm(f"[ELB] my-alb RequestCount > 1000 (TagName: {arn})", result)
        assert "ELB" in result
        assert arn in result["ELB"]

    def test_new_format_tg(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc"
        result = {}
        _classify_alarm(f"[TG] my-tg HealthyHostCount < 1 (TagName: {arn})", result)
        assert "TG" in result
        assert arn in result["TG"]

    def test_legacy_format_ec2(self):
        result = {}
        _classify_alarm("i-0abcdef1234567890-CPU-prod", result)
        assert "EC2" in result
        assert "i-0abcdef1234567890" in result["EC2"]

    def test_unrecognized_format_ignored(self):
        result = {}
        _classify_alarm("some-random-alarm-name", result)
        assert result == {}

    def test_mixed_formats_accumulated(self):
        """새 포맷과 레거시 포맷이 같은 result에 누적."""
        result = {}
        _classify_alarm("[EC2] srv CPU > 80% (TagName: i-001)", result)
        _classify_alarm("i-001-CPU-prod", result)
        _classify_alarm("[RDS] db CPU > 80% (TagName: db-001)", result)
        assert "EC2" in result
        assert "RDS" in result
        assert len(result["EC2"]["i-001"]) == 2
        assert len(result["RDS"]["db-001"]) == 1

    def test_new_format_alb(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        result = {}
        _classify_alarm(f"[ALB] my-alb RequestCount > 5000 (TagName: {arn})", result)
        assert "ALB" in result
        assert arn in result["ALB"]

    def test_new_format_nlb(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        result = {}
        _classify_alarm(f"[NLB] my-nlb ProcessedBytes > 1000 (TagName: {arn})", result)
        assert "NLB" in result
        assert arn in result["NLB"]


class TestCleanupOrphanAlarms:
    """_cleanup_orphan_alarms 통합 테스트 — collector-based 고아 알람 정리."""

    def test_ec2_orphan_deleted(self):
        """terminated EC2 인스턴스의 알람 삭제."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[EC2] srv CPU > 80% (TagName: i-dead)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.ec2_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert "[EC2] srv CPU > 80% (TagName: i-dead)" in deleted
        mock_cw.delete_alarms.assert_called_once()

    def test_rds_orphan_deleted(self):
        """존재하지 않는 RDS 인스턴스의 알람 삭제."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[RDS] my-db CPUUtilization > 80% (TagName: db-gone)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.rds_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert "[RDS] my-db CPUUtilization > 80% (TagName: db-gone)" in deleted

    def test_elb_orphan_deleted(self):
        """존재하지 않는 ELB의 알람 삭제."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": f"[ELB] my-alb RequestCount > 1000 (TagName: {arn})"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.elb_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert len(deleted) == 1
        assert arn in deleted[0]

    def test_alive_resources_not_deleted(self):
        """존재하는 리소스의 알람은 삭제하지 않음."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[EC2] srv CPU > 80% (TagName: i-alive)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.ec2_collector.resolve_alive_ids",
                   return_value={"i-alive"}):
            deleted = _cleanup_orphan_alarms()

        assert deleted == []
        mock_cw.delete_alarms.assert_not_called()

    def test_legacy_ec2_orphan_still_handled(self):
        """레거시 포맷 EC2 알람도 고아 정리 대상."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "i-0dead1234567890ab-CPU-prod"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.ec2_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert "i-0dead1234567890ab-CPU-prod" in deleted

    def test_no_alarms_returns_empty(self):
        """알람이 없으면 빈 리스트 반환."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw):
            deleted = _cleanup_orphan_alarms()

        assert deleted == []

    def test_alb_orphan_deleted(self):
        """존재하지 않는 ALB의 알람 삭제."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": f"[ALB] my-alb RequestCount > 5000 (TagName: {arn})"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.elb_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert len(deleted) == 1
        assert arn in deleted[0]

    def test_nlb_orphan_deleted(self):
        """존재하지 않는 NLB의 알람 삭제."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def"
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": f"[NLB] my-nlb ProcessedBytes > 1000 (TagName: {arn})"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.elb_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert len(deleted) == 1
        assert arn in deleted[0]


# ──────────────────────────────────────────────
# Task 7.1: _process_resource() AuroraRDS 라우팅 검증
# Requirements: 6.1, 6.2, 6.3
# ──────────────────────────────────────────────


class TestProcessResourceAuroraRDS:
    """_process_resource() AuroraRDS 라우팅 및 임계치 비교 검증."""

    def test_aurora_rds_routes_to_get_aurora_metrics(self):
        """resource_type='AuroraRDS' → collector_mod.get_aurora_metrics() 호출."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"CPU": 50.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert"):
            _process_resource(
                "aurora-db-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        collector_mod.get_aurora_metrics.assert_called_once_with(
            "aurora-db-001", {"Monitoring": "on"},
        )
        # get_metrics should NOT be called for AuroraRDS
        collector_mod.get_metrics.assert_not_called()

    def test_aurora_rds_free_local_storage_less_than_threshold_alerts(self):
        """FreeLocalStorageGB < threshold → 알림 발송 (낮을수록 위험)."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"FreeLocalStorageGB": 5.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=10.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-db-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="aurora-db-001",
            resource_type="AuroraRDS",
            metric_name="FreeLocalStorageGB",
            current_value=5.0,
            threshold=10.0,
            tag_name="",
        )

    def test_aurora_rds_free_local_storage_above_threshold_no_alert(self):
        """FreeLocalStorageGB >= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"FreeLocalStorageGB": 15.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=10.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-db-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()

    def test_aurora_rds_no_metrics_returns_zero(self):
        """AuroraRDS 메트릭 없으면 알림 0건."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = None

        with patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-db-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()


# ──────────────────────────────────────────────
# Task 7.3: _cleanup_orphan_alarms() AuroraRDS alive_checker 검증
# Requirements: 7.1, 7.2, 7.3
# ──────────────────────────────────────────────


class TestCleanupOrphanAlarmsAuroraRDS:
    """AuroraRDS 고아 알람 정리 검증."""

    def test_aurora_rds_orphan_alarm_deleted(self):
        """삭제된 Aurora DB 인스턴스의 알람이 고아로 삭제됨."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[AuroraRDS] my-aurora FreeLocalStorage < 10GB (TagName: aurora-db-gone)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.rds_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert "[AuroraRDS] my-aurora FreeLocalStorage < 10GB (TagName: aurora-db-gone)" in deleted
        mock_cw.delete_alarms.assert_called_once()

    def test_aurora_rds_alive_instance_not_deleted(self):
        """존재하는 Aurora DB 인스턴스의 알람은 삭제하지 않음."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[AuroraRDS] my-aurora CPU > 80% (TagName: aurora-db-alive)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.rds_collector.resolve_alive_ids",
                   return_value={"aurora-db-alive"}):
            deleted = _cleanup_orphan_alarms()

        assert deleted == []
        mock_cw.delete_alarms.assert_not_called()

    def test_aurora_rds_uses_rds_collector_resolve_alive_ids(self):
        """_RESOURCE_TYPE_TO_COLLECTOR['AuroraRDS'] == rds_collector 검증."""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        from common.collectors import rds as rds_mod

        assert _RESOURCE_TYPE_TO_COLLECTOR["AuroraRDS"] is rds_mod

        # Also verify via integration: AuroraRDS alarms trigger rds_collector.resolve_alive_ids
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[AuroraRDS] aurora-inst CPU > 80% (TagName: aurora-db-001)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.rds_collector.resolve_alive_ids",
                   return_value=set()) as mock_resolve:
            deleted = _cleanup_orphan_alarms()

        mock_resolve.assert_called_once_with({"aurora-db-001"})
        assert len(deleted) == 1


# ──────────────────────────────────────────────
# Task 12.1: _process_resource() 신규 메트릭 임계치 비교 검증
# Requirements: 9.1, 10.1, 10.2
# ──────────────────────────────────────────────


class TestProcessResourceNewAuroraMetrics:
    """_process_resource() 신규 Aurora 메트릭 greater-than 비교 검증."""

    def test_reader_replica_lag_above_threshold_alerts(self):
        """ReaderReplicaLag > threshold → 알림 발송 (높을수록 위험)."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ReaderReplicaLag": 3000000.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=2000000.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-reader-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="aurora-reader-001",
            resource_type="AuroraRDS",
            metric_name="ReaderReplicaLag",
            current_value=3000000.0,
            threshold=2000000.0,
            tag_name="",
        )

    def test_reader_replica_lag_below_threshold_no_alert(self):
        """ReaderReplicaLag <= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ReaderReplicaLag": 1000000.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=2000000.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-reader-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()

    def test_acu_utilization_above_threshold_alerts(self):
        """ACUUtilization > threshold → 알림 발송 (높을수록 위험)."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ACUUtilization": 95.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-sv2-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="aurora-sv2-001",
            resource_type="AuroraRDS",
            metric_name="ACUUtilization",
            current_value=95.0,
            threshold=80.0,
            tag_name="",
        )

    def test_acu_utilization_below_threshold_no_alert(self):
        """ACUUtilization <= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ACUUtilization": 50.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-sv2-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()

    def test_serverless_database_capacity_above_threshold_alerts(self):
        """ServerlessDatabaseCapacity > threshold → 알림 발송 (높을수록 위험)."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ServerlessDatabaseCapacity": 150.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=128.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-sv2-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="aurora-sv2-001",
            resource_type="AuroraRDS",
            metric_name="ServerlessDatabaseCapacity",
            current_value=150.0,
            threshold=128.0,
            tag_name="",
        )

    def test_serverless_database_capacity_below_threshold_no_alert(self):
        """ServerlessDatabaseCapacity <= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_aurora_metrics.return_value = {"ServerlessDatabaseCapacity": 64.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=128.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "aurora-sv2-001", "AuroraRDS", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()


# ──────────────────────────────────────────────
# Task 7.1: Daily Monitor DocDB 통합 테스트
# Validates: Requirements 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3
# ──────────────────────────────────────────────


class TestDailyMonitorDocDBIntegration:
    """Daily Monitor DocDB Collector 통합 검증."""

    def test_collector_modules_includes_docdb(self):
        """_COLLECTOR_MODULES에 docdb_collector 포함 검증 — Req 7.1"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.docdb" in module_names, (
            f"docdb_collector not in _COLLECTOR_MODULES: {module_names}"
        )

    def test_alive_checkers_includes_docdb(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'DocDB' 키 존재 검증 — Req 8.1"""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[DocDB] my-docdb CPU > 80% (TagName: docdb-gone)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.docdb_collector.resolve_alive_ids",
                   return_value=set()):
            deleted = _cleanup_orphan_alarms()

        assert "[DocDB] my-docdb CPU > 80% (TagName: docdb-gone)" in deleted

    def test_docdb_alive_instance_not_deleted(self):
        """존재하는 DocDB 인스턴스의 알람은 삭제하지 않음 — Req 8.3"""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "[DocDB] my-docdb CPU > 80% (TagName: docdb-alive)"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("daily_monitor.lambda_handler._get_cw_client", return_value=mock_cw), \
             patch("daily_monitor.lambda_handler.docdb_collector.resolve_alive_ids",
                   return_value={"docdb-alive"}):
            deleted = _cleanup_orphan_alarms()

        assert deleted == []

    def test_classify_alarm_docdb_format(self):
        """_classify_alarm()이 [DocDB] 접두사 알람을 올바르게 분류 — Req 8.2"""
        result = {}
        _classify_alarm("[DocDB] my-docdb CPU > 80% (TagName: docdb-inst-1)", result)
        assert "DocDB" in result
        assert "docdb-inst-1" in result["DocDB"]

    def test_process_resource_docdb_uses_get_metrics(self):
        """DocDB 리소스는 기존 else 분기에서 get_metrics() 호출 — Req 7.3"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"CPU": 50.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert"):
            _process_resource(
                "docdb-inst-1", "DocDB", {"Monitoring": "on"}, collector_mod,
            )

        collector_mod.get_metrics.assert_called_once_with(
            "docdb-inst-1", {"Monitoring": "on"},
        )

    def test_docdb_free_memory_below_threshold_alerts(self):
        """DocDB FreeMemoryGB < threshold → 알림 발송 (낮을수록 위험) — Req 7.4"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"FreeMemoryGB": 1.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=2.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "docdb-inst-1", "DocDB", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="docdb-inst-1",
            resource_type="DocDB",
            metric_name="FreeMemoryGB",
            current_value=1.0,
            threshold=2.0,
            tag_name="",
        )

    def test_docdb_free_local_storage_below_threshold_alerts(self):
        """DocDB FreeLocalStorageGB < threshold → 알림 발송 (낮을수록 위험) — Req 7.4"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"FreeLocalStorageGB": 5.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=10.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "docdb-inst-1", "DocDB", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once()

    def test_docdb_cpu_above_threshold_alerts(self):
        """DocDB CPU > threshold → 알림 발송 — Req 7.3"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"CPU": 95.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=80.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "docdb-inst-1", "DocDB", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once()


# ──────────────────────────────────────────────
# Task 9.1: Daily Monitor 8개 신규 리소스 통합 테스트
# Validates: Requirements 1.5, 2.6, 3-A.4, 4.6, 5.5, 6.5, 7.5, 8.6, 12.1, 12.3
# ──────────────────────────────────────────────


class TestNewResourceDailyMonitorIntegration:
    """Daily Monitor 8개 신규 Collector 통합 검증."""

    # ── _COLLECTOR_MODULES 검증 ──

    def test_collector_modules_includes_lambda(self):
        """_COLLECTOR_MODULES에 lambda_collector 포함 — Req 1.5"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.lambda_fn" in module_names

    def test_collector_modules_includes_vpn(self):
        """_COLLECTOR_MODULES에 vpn_collector 포함 — Req 2.6"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.vpn" in module_names

    def test_collector_modules_includes_apigw(self):
        """_COLLECTOR_MODULES에 apigw_collector 포함 — Req 3-A.4"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.apigw" in module_names

    def test_collector_modules_includes_acm(self):
        """_COLLECTOR_MODULES에 acm_collector 포함 — Req 4.6"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.acm" in module_names

    def test_collector_modules_includes_backup(self):
        """_COLLECTOR_MODULES에 backup_collector 포함 — Req 5.5"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.backup" in module_names

    def test_collector_modules_includes_mq(self):
        """_COLLECTOR_MODULES에 mq_collector 포함 — Req 6.5"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.mq" in module_names

    def test_collector_modules_includes_clb(self):
        """_COLLECTOR_MODULES에 clb_collector 포함 — Req 7.5"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.clb" in module_names

    def test_collector_modules_includes_opensearch(self):
        """_COLLECTOR_MODULES에 opensearch_collector 포함 — Req 8.6"""
        from daily_monitor.lambda_handler import _COLLECTOR_MODULES
        module_names = [m.__name__ for m in _COLLECTOR_MODULES]
        assert "common.collectors.opensearch" in module_names

    # ── _RESOURCE_TYPE_TO_COLLECTOR 검증 ──

    def test_resource_type_to_collector_has_lambda_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'Lambda' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "Lambda" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_vpn_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'VPN' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "VPN" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_apigw_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'APIGW' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "APIGW" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_acm_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'ACM' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "ACM" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_backup_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'Backup' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "Backup" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_mq_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'MQ' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "MQ" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_clb_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'CLB' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "CLB" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_resource_type_to_collector_has_opensearch_key(self):
        """_RESOURCE_TYPE_TO_COLLECTOR에 'OpenSearch' 키 존재 — Req 12.1"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert "OpenSearch" in _RESOURCE_TYPE_TO_COLLECTOR

    def test_collector_lambda_has_resolve_alive_ids(self):
        """Lambda collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["Lambda"], "resolve_alive_ids", None))

    def test_collector_vpn_has_resolve_alive_ids(self):
        """VPN collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["VPN"], "resolve_alive_ids", None))

    def test_collector_apigw_has_resolve_alive_ids(self):
        """APIGW collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["APIGW"], "resolve_alive_ids", None))

    def test_collector_acm_has_resolve_alive_ids(self):
        """ACM collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["ACM"], "resolve_alive_ids", None))

    def test_collector_backup_has_resolve_alive_ids(self):
        """Backup collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["Backup"], "resolve_alive_ids", None))

    def test_collector_mq_has_resolve_alive_ids(self):
        """MQ collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["MQ"], "resolve_alive_ids", None))

    def test_collector_clb_has_resolve_alive_ids(self):
        """CLB collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["CLB"], "resolve_alive_ids", None))

    def test_collector_opensearch_has_resolve_alive_ids(self):
        """OpenSearch collector에 resolve_alive_ids 메서드 존재 — Req 12.3"""
        from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR
        assert callable(getattr(_RESOURCE_TYPE_TO_COLLECTOR["OpenSearch"], "resolve_alive_ids", None))

    # ── "낮을수록 위험" 메트릭 세트 검증 ──

    def test_tunnel_state_lower_is_dangerous(self):
        """TunnelState < threshold → 알림 발송 (낮을수록 위험) — Req 2.6"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"TunnelState": 0.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=1.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "vpn-001", "VPN", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="vpn-001",
            resource_type="VPN",
            metric_name="TunnelState",
            current_value=0.0,
            threshold=1.0,
            tag_name="",
        )

    def test_tunnel_state_above_threshold_no_alert(self):
        """TunnelState >= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"TunnelState": 1.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=1.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "vpn-001", "VPN", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()

    def test_days_to_expiry_lower_is_dangerous(self):
        """DaysToExpiry < threshold → 알림 발송 (낮을수록 위험) — Req 4.6"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"DaysToExpiry": 7.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=14.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "arn:aws:acm:us-east-1:123:certificate/abc", "ACM",
                {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="arn:aws:acm:us-east-1:123:certificate/abc",
            resource_type="ACM",
            metric_name="DaysToExpiry",
            current_value=7.0,
            threshold=14.0,
            tag_name="",
        )

    def test_days_to_expiry_above_threshold_no_alert(self):
        """DaysToExpiry >= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"DaysToExpiry": 30.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=14.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "arn:aws:acm:us-east-1:123:certificate/abc", "ACM",
                {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()

    def test_os_free_storage_space_lower_is_dangerous(self):
        """OSFreeStorageSpace < threshold → 알림 발송 (낮을수록 위험) — Req 8.6"""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"OSFreeStorageSpace": 10000.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=20480.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "my-domain", "OpenSearch", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 1
        mock_alert.assert_called_once_with(
            resource_id="my-domain",
            resource_type="OpenSearch",
            metric_name="OSFreeStorageSpace",
            current_value=10000.0,
            threshold=20480.0,
            tag_name="",
        )

    def test_os_free_storage_space_above_threshold_no_alert(self):
        """OSFreeStorageSpace >= threshold → 알림 미발송."""
        collector_mod = MagicMock()
        collector_mod.get_metrics.return_value = {"OSFreeStorageSpace": 30000.0}

        with patch("daily_monitor.lambda_handler.get_threshold", return_value=20480.0), \
             patch("daily_monitor.lambda_handler.send_alert") as mock_alert:
            alerts = _process_resource(
                "my-domain", "OpenSearch", {"Monitoring": "on"}, collector_mod,
            )

        assert alerts == 0
        mock_alert.assert_not_called()
