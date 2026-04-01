"""
알람 정의 + 매핑 테이블 테스트

리소스 타입별 알람 정의(_get_alarm_defs), 상수 매핑(_HARDCODED_METRIC_KEYS,
_NAMESPACE_MAP, _DIMENSION_KEY_MAP, _METRIC_DISPLAY, _metric_name_to_key) 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from common import HARDCODED_DEFAULTS
from common.alarm_manager import (
    _build_dimensions,
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
    _HARDCODED_METRIC_KEYS,
    _METRIC_DISPLAY,
    _metric_name_to_key,
    _resolve_tg_namespace,
    create_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    from common._clients import _get_cw_client
    _get_cw_client.cache_clear()
    yield
    _get_cw_client.cache_clear()


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")


# ──────────────────────────────────────────────
# EC2 StatusCheckFailed 알람 정의 검증 (TDD Red)
# ──────────────────────────────────────────────

def test_ec2_status_check_failed_alarm_def():
    """EC2 StatusCheckFailed 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
    """
    # _get_alarm_defs("EC2") → 4개 (CPU, Memory, Disk, StatusCheckFailed)
    defs = _get_alarm_defs("EC2")
    assert len(defs) == 4
    metrics = {d["metric"] for d in defs}
    assert "StatusCheckFailed" in metrics

    # _HARDCODED_METRIC_KEYS["EC2"]에 StatusCheckFailed 포함
    assert _HARDCODED_METRIC_KEYS["EC2"] == {"CPU", "Memory", "Disk", "StatusCheckFailed"}

    # _METRIC_DISPLAY 매핑 검증
    assert _METRIC_DISPLAY["StatusCheckFailed"] == ("StatusCheckFailed", ">", "")

    # _metric_name_to_key 변환 검증
    assert _metric_name_to_key("StatusCheckFailed") == "StatusCheckFailed"

    # HARDCODED_DEFAULTS 기본 임계치 검증
    assert HARDCODED_DEFAULTS["StatusCheckFailed"] == 0.0

    # StatusCheckFailed 알람 정의 상세 검증
    scf_def = next(d for d in defs if d["metric"] == "StatusCheckFailed")
    assert scf_def["stat"] == "Maximum"
    assert scf_def["comparison"] == "GreaterThanThreshold"
    assert scf_def["namespace"] == "AWS/EC2"
    assert scf_def["dimension_key"] == "InstanceId"


def test_rds_read_write_latency_alarm_def():
    """RDS ReadLatency/WriteLatency 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """
    defs = _get_alarm_defs("RDS")
    assert len(defs) == 7
    metrics = {d["metric"] for d in defs}
    assert "ReadLatency" in metrics
    assert "WriteLatency" in metrics

    assert _HARDCODED_METRIC_KEYS["RDS"] == {
        "CPU", "FreeMemoryGB", "FreeStorageGB", "Connections",
        "ReadLatency", "WriteLatency", "ConnectionAttempts",
    }

    assert _METRIC_DISPLAY["ReadLatency"] == ("ReadLatency", ">", "s")
    assert _METRIC_DISPLAY["WriteLatency"] == ("WriteLatency", ">", "s")

    assert _metric_name_to_key("ReadLatency") == "ReadLatency"
    assert _metric_name_to_key("WriteLatency") == "WriteLatency"

    assert HARDCODED_DEFAULTS["ReadLatency"] == 0.02
    assert HARDCODED_DEFAULTS["WriteLatency"] == 0.02

    rl_def = next(d for d in defs if d["metric"] == "ReadLatency")
    assert rl_def["stat"] == "Average"
    assert rl_def["comparison"] == "GreaterThanThreshold"
    assert rl_def["namespace"] == "AWS/RDS"
    assert rl_def["dimension_key"] == "DBInstanceIdentifier"

    wl_def = next(d for d in defs if d["metric"] == "WriteLatency")
    assert wl_def["stat"] == "Average"
    assert wl_def["comparison"] == "GreaterThanThreshold"
    assert wl_def["namespace"] == "AWS/RDS"
    assert wl_def["dimension_key"] == "DBInstanceIdentifier"


def test_rds_connection_attempts_alarm_def():
    """RDS ConnectionAttempts 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
    """
    defs = _get_alarm_defs("RDS")
    assert len(defs) == 7
    metrics = {d["metric"] for d in defs}
    assert "ConnectionAttempts" in metrics

    assert _HARDCODED_METRIC_KEYS["RDS"] == {
        "CPU", "FreeMemoryGB", "FreeStorageGB", "Connections",
        "ReadLatency", "WriteLatency", "ConnectionAttempts",
    }

    assert _METRIC_DISPLAY["ConnectionAttempts"] == ("ConnectionAttempts", ">", "")
    assert _metric_name_to_key("ConnectionAttempts") == "ConnectionAttempts"
    assert HARDCODED_DEFAULTS["ConnectionAttempts"] == 500.0

    ca_def = next(d for d in defs if d["metric"] == "ConnectionAttempts")
    assert ca_def["dimension_key"] == "DBInstanceIdentifier"
    assert ca_def["stat"] == "Sum"
    assert ca_def["comparison"] == "GreaterThanThreshold"
    assert ca_def["namespace"] == "AWS/RDS"


def test_alb_elb5xx_target_response_time_alarm_def():
    """ALB ELB5XX/TargetResponseTime 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 8.4
    """
    defs = _get_alarm_defs("ALB")
    assert len(defs) == 5
    metrics = {d["metric"] for d in defs}
    assert "ELB5XX" in metrics
    assert "TargetResponseTime" in metrics

    assert _HARDCODED_METRIC_KEYS["ALB"] == {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}

    assert _METRIC_DISPLAY["ELB5XX"] == ("HTTPCode_ELB_5XX_Count", ">", "")
    assert _METRIC_DISPLAY["TargetResponseTime"] == ("TargetResponseTime", ">", "s")

    assert _metric_name_to_key("HTTPCode_ELB_5XX_Count") == "ELB5XX"
    assert _metric_name_to_key("TargetResponseTime") == "TargetResponseTime"

    assert HARDCODED_DEFAULTS["ELB5XX"] == 50.0
    assert HARDCODED_DEFAULTS["TargetResponseTime"] == 5.0

    elb5xx_def = next(d for d in defs if d["metric"] == "ELB5XX")
    assert elb5xx_def["dimension_key"] == "LoadBalancer"
    assert elb5xx_def["stat"] == "Sum"
    assert elb5xx_def["namespace"] == "AWS/ApplicationELB"

    trt_def = next(d for d in defs if d["metric"] == "TargetResponseTime")
    assert trt_def["dimension_key"] == "LoadBalancer"
    assert trt_def["stat"] == "Average"
    assert trt_def["namespace"] == "AWS/ApplicationELB"


def test_alb_elb4xx_target_connection_error_alarm_def():
    """ALB ELB4XX/TargetConnectionError 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """
    defs = _get_alarm_defs("ALB")
    assert len(defs) == 5
    metrics = {d["metric"] for d in defs}
    assert metrics == {"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}

    assert _HARDCODED_METRIC_KEYS["ALB"] == {
        "RequestCount", "ELB5XX", "TargetResponseTime",
        "ELB4XX", "TargetConnectionError",
    }

    assert _METRIC_DISPLAY["ELB4XX"] == ("HTTPCode_ELB_4XX_Count", ">", "")
    assert _METRIC_DISPLAY["TargetConnectionError"] == ("TargetConnectionErrorCount", ">", "")

    assert _metric_name_to_key("HTTPCode_ELB_4XX_Count") == "ELB4XX"
    assert _metric_name_to_key("TargetConnectionErrorCount") == "TargetConnectionError"

    assert HARDCODED_DEFAULTS["ELB4XX"] == 100.0
    assert HARDCODED_DEFAULTS["TargetConnectionError"] == 50.0

    elb4xx_def = next(d for d in defs if d["metric"] == "ELB4XX")
    assert elb4xx_def["dimension_key"] == "LoadBalancer"
    assert elb4xx_def["stat"] == "Sum"
    assert elb4xx_def["comparison"] == "GreaterThanThreshold"
    assert elb4xx_def["namespace"] == "AWS/ApplicationELB"

    tce_def = next(d for d in defs if d["metric"] == "TargetConnectionError")
    assert tce_def["dimension_key"] == "LoadBalancer"
    assert tce_def["stat"] == "Sum"
    assert tce_def["comparison"] == "GreaterThanThreshold"
    assert tce_def["namespace"] == "AWS/ApplicationELB"


def test_nlb_tcp_reset_alarm_def():
    """NLB TCPClientReset/TCPTargetReset 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    defs = _get_alarm_defs("NLB")
    assert len(defs) == 5
    metrics = {d["metric"] for d in defs}
    assert metrics == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}

    assert _HARDCODED_METRIC_KEYS["NLB"] == {
        "ProcessedBytes", "ActiveFlowCount", "NewFlowCount",
        "TCPClientReset", "TCPTargetReset",
    }

    assert _METRIC_DISPLAY["TCPClientReset"] == ("TCP_Client_Reset_Count", ">", "")
    assert _METRIC_DISPLAY["TCPTargetReset"] == ("TCP_Target_Reset_Count", ">", "")

    assert _metric_name_to_key("TCP_Client_Reset_Count") == "TCPClientReset"
    assert _metric_name_to_key("TCP_Target_Reset_Count") == "TCPTargetReset"

    assert HARDCODED_DEFAULTS["TCPClientReset"] == 100.0
    assert HARDCODED_DEFAULTS["TCPTargetReset"] == 100.0

    tcr_def = next(d for d in defs if d["metric"] == "TCPClientReset")
    assert tcr_def["dimension_key"] == "LoadBalancer"
    assert tcr_def["stat"] == "Sum"
    assert tcr_def["namespace"] == "AWS/NetworkELB"

    ttr_def = next(d for d in defs if d["metric"] == "TCPTargetReset")
    assert ttr_def["dimension_key"] == "LoadBalancer"
    assert ttr_def["stat"] == "Sum"
    assert ttr_def["namespace"] == "AWS/NetworkELB"


def test_tg_request_count_response_time_alarm_def():
    """TG RequestCountPerTarget/TGResponseTime 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.7, 5.8, 5.9, 5.10
    """
    defs = _get_alarm_defs("TG")
    assert len(defs) == 4
    metrics = {d["metric"] for d in defs}
    assert metrics == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}

    assert _HARDCODED_METRIC_KEYS["TG"] == {
        "HealthyHostCount", "UnHealthyHostCount",
        "RequestCountPerTarget", "TGResponseTime",
    }

    assert _METRIC_DISPLAY["RequestCountPerTarget"] == ("RequestCountPerTarget", ">", "")
    assert _METRIC_DISPLAY["TGResponseTime"] == ("TargetResponseTime", ">", "s")

    assert _metric_name_to_key("RequestCountPerTarget") == "RequestCountPerTarget"

    assert HARDCODED_DEFAULTS["RequestCountPerTarget"] == 1000.0
    assert HARDCODED_DEFAULTS["TGResponseTime"] == 5.0

    rcpt_def = next(d for d in defs if d["metric"] == "RequestCountPerTarget")
    assert rcpt_def["dimension_key"] == "TargetGroup"
    assert rcpt_def["stat"] == "Sum"
    assert rcpt_def["namespace"] == "AWS/ApplicationELB"

    tgrt_def = next(d for d in defs if d["metric"] == "TGResponseTime")
    assert tgrt_def["dimension_key"] == "TargetGroup"
    assert tgrt_def["stat"] == "Average"
    assert tgrt_def["namespace"] == "AWS/ApplicationELB"


# ──────────────────────────────────────────────
# AuroraRDS 알람 정의 검증 (Task 4.1 - TDD Red)
# ──────────────────────────────────────────────

def test_aurora_rds_alarm_defs():
    """_get_alarm_defs('AuroraRDS') → Provisioned Writer (w/ readers) 5개 정의 반환 검증.
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    tags = {
        "_is_serverless_v2": "false",
        "_is_cluster_writer": "true",
        "_has_readers": "true",
    }
    defs = _get_alarm_defs("AuroraRDS", tags)
    assert len(defs) == 5
    metrics = {d["metric"] for d in defs}
    assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag"}

    for d in defs:
        assert d["namespace"] == "AWS/RDS"
        assert d["dimension_key"] == "DBInstanceIdentifier"
        assert d["period"] == 300
        assert d["evaluation_periods"] == 1

    cpu_def = next(d for d in defs if d["metric"] == "CPU")
    assert cpu_def["stat"] == "Average"
    assert cpu_def["comparison"] == "GreaterThanThreshold"
    assert cpu_def["metric_name"] == "CPUUtilization"

    mem_def = next(d for d in defs if d["metric"] == "FreeMemoryGB")
    assert mem_def["stat"] == "Average"
    assert mem_def["comparison"] == "LessThanThreshold"
    assert mem_def["metric_name"] == "FreeableMemory"
    assert mem_def["transform_threshold"](2.0) == 2.0 * 1073741824

    conn_def = next(d for d in defs if d["metric"] == "Connections")
    assert conn_def["stat"] == "Average"
    assert conn_def["comparison"] == "GreaterThanThreshold"
    assert conn_def["metric_name"] == "DatabaseConnections"

    storage_def = next(d for d in defs if d["metric"] == "FreeLocalStorageGB")
    assert storage_def["stat"] == "Average"
    assert storage_def["comparison"] == "LessThanThreshold"
    assert storage_def["metric_name"] == "FreeLocalStorage"
    assert storage_def["transform_threshold"](10.0) == 10737418240

    lag_def = next(d for d in defs if d["metric"] == "ReplicaLag")
    assert lag_def["stat"] == "Maximum"
    assert lag_def["comparison"] == "GreaterThanThreshold"
    assert lag_def["metric_name"] == "AuroraReplicaLagMaximum"


def test_aurora_rds_constant_mappings():
    """AuroraRDS 상수 매핑 업데이트 검증.
    Validates: Requirements 5.3, 5.4
    """
    from common.alarm_manager import _NAMESPACE_MAP, _DIMENSION_KEY_MAP

    assert "AuroraRDS" in _HARDCODED_METRIC_KEYS
    assert _HARDCODED_METRIC_KEYS["AuroraRDS"] == {
        "CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag",
        "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity",
    }

    assert _NAMESPACE_MAP["AuroraRDS"] == ["AWS/RDS"]
    assert _DIMENSION_KEY_MAP["AuroraRDS"] == "DBInstanceIdentifier"

    assert _METRIC_DISPLAY["FreeLocalStorageGB"] == ("FreeLocalStorage", "<", "GB")
    assert _METRIC_DISPLAY["ReplicaLag"] == ("AuroraReplicaLagMaximum", ">", "μs")

    assert _metric_name_to_key("FreeLocalStorage") == "FreeLocalStorageGB"
    assert _metric_name_to_key("AuroraReplicaLagMaximum") == "ReplicaLag"


class TestAuroraAlarmVariantRouting:
    """Aurora 인스턴스 변형별 알람 라우팅 검증.
    Validates: Requirements 2.1, 2.2, 3.1, 3.2, 4.4, 7.1, 7.2, 7.3, 11.1, 11.2
    """

    def test_provisioned_writer_with_readers(self):
        tags = {"_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "true"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag"}

    def test_provisioned_writer_no_readers(self):
        tags = {"_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "false"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB"}

    def test_provisioned_reader(self):
        tags = {"_is_serverless_v2": "false", "_is_cluster_writer": "false", "_has_readers": "true"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReaderReplicaLag"}

    def test_serverless_v2_writer_with_readers(self):
        tags = {"_is_serverless_v2": "true", "_is_cluster_writer": "true", "_has_readers": "true"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections", "ReplicaLag"}

    def test_serverless_v2_writer_no_readers(self):
        tags = {"_is_serverless_v2": "true", "_is_cluster_writer": "true", "_has_readers": "false"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections"}

    def test_serverless_v2_reader(self):
        tags = {"_is_serverless_v2": "true", "_is_cluster_writer": "false", "_has_readers": "true"}
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections", "ReaderReplicaLag"}

    def test_aurora_reader_replica_lag_alarm_def_schema(self):
        from common.alarm_manager import _AURORA_READER_REPLICA_LAG
        assert _AURORA_READER_REPLICA_LAG["metric"] == "ReaderReplicaLag"
        assert _AURORA_READER_REPLICA_LAG["namespace"] == "AWS/RDS"
        assert _AURORA_READER_REPLICA_LAG["metric_name"] == "AuroraReplicaLag"
        assert _AURORA_READER_REPLICA_LAG["dimension_key"] == "DBInstanceIdentifier"
        assert _AURORA_READER_REPLICA_LAG["stat"] == "Maximum"
        assert _AURORA_READER_REPLICA_LAG["comparison"] == "GreaterThanThreshold"
        assert _AURORA_READER_REPLICA_LAG["period"] == 300
        assert _AURORA_READER_REPLICA_LAG["evaluation_periods"] == 1

    def test_aurora_acu_utilization_alarm_def_schema(self):
        from common.alarm_manager import _AURORA_ACU_UTILIZATION
        assert _AURORA_ACU_UTILIZATION["metric"] == "ACUUtilization"
        assert _AURORA_ACU_UTILIZATION["namespace"] == "AWS/RDS"
        assert _AURORA_ACU_UTILIZATION["metric_name"] == "ACUUtilization"
        assert _AURORA_ACU_UTILIZATION["dimension_key"] == "DBInstanceIdentifier"
        assert _AURORA_ACU_UTILIZATION["stat"] == "Average"
        assert _AURORA_ACU_UTILIZATION["comparison"] == "GreaterThanThreshold"
        assert _AURORA_ACU_UTILIZATION["period"] == 300
        assert _AURORA_ACU_UTILIZATION["evaluation_periods"] == 1

    def test_aurora_serverless_capacity_alarm_def_schema(self):
        from common.alarm_manager import _AURORA_SERVERLESS_CAPACITY
        assert _AURORA_SERVERLESS_CAPACITY["metric"] == "ServerlessDatabaseCapacity"
        assert _AURORA_SERVERLESS_CAPACITY["namespace"] == "AWS/RDS"
        assert _AURORA_SERVERLESS_CAPACITY["metric_name"] == "ServerlessDatabaseCapacity"
        assert _AURORA_SERVERLESS_CAPACITY["dimension_key"] == "DBInstanceIdentifier"
        assert _AURORA_SERVERLESS_CAPACITY["stat"] == "Average"
        assert _AURORA_SERVERLESS_CAPACITY["comparison"] == "GreaterThanThreshold"
        assert _AURORA_SERVERLESS_CAPACITY["period"] == 300
        assert _AURORA_SERVERLESS_CAPACITY["evaluation_periods"] == 1

    def test_aurora_no_tags_falls_back_to_base(self):
        defs = _get_alarm_defs("AuroraRDS", {})
        metrics = {d["metric"] for d in defs}
        assert "CPU" in metrics
        assert "FreeMemoryGB" in metrics
        assert "Connections" in metrics


class TestAuroraConstantMappings:
    """Aurora 신규 메트릭 상수 매핑 검증.
    Validates: Requirements 3.5, 7.6, 12.3
    """

    def test_metric_display_reader_replica_lag(self):
        assert "ReaderReplicaLag" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ReaderReplicaLag"] == ("AuroraReplicaLag", ">", "μs")

    def test_metric_display_acu_utilization(self):
        assert "ACUUtilization" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ACUUtilization"] == ("ACUUtilization", ">", "%")

    def test_metric_display_serverless_database_capacity(self):
        assert "ServerlessDatabaseCapacity" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ServerlessDatabaseCapacity"] == ("ServerlessDatabaseCapacity", ">", "ACU")

    def test_hardcoded_metric_keys_aurora_rds_8_keys(self):
        expected = {
            "CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB",
            "ReplicaLag", "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity",
        }
        assert _HARDCODED_METRIC_KEYS["AuroraRDS"] == expected

    def test_metric_name_to_key_aurora_replica_lag(self):
        assert _metric_name_to_key("AuroraReplicaLag") == "ReaderReplicaLag"

    def test_metric_name_to_key_acu_utilization(self):
        assert _metric_name_to_key("ACUUtilization") == "ACUUtilization"

    def test_metric_name_to_key_serverless_database_capacity(self):
        assert _metric_name_to_key("ServerlessDatabaseCapacity") == "ServerlessDatabaseCapacity"


# ──────────────────────────────────────────────
# DocDB 알람 정의 검증
# ──────────────────────────────────────────────

class TestDocDBAlarmDefs:
    """DocDB 알람 정의 및 매핑 테이블 검증.
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 6.1, 6.2, 6.3, 6.4
    """

    def test_get_alarm_defs_docdb_returns_three(self):
        defs = _get_alarm_defs("DocDB")
        assert len(defs) == 3

    def test_get_alarm_defs_docdb_metric_keys(self):
        defs = _get_alarm_defs("DocDB")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections"}

    def test_get_alarm_defs_docdb_namespace(self):
        defs = _get_alarm_defs("DocDB")
        for d in defs:
            assert d["namespace"] == "AWS/DocDB", f"{d['metric']} namespace mismatch"

    def test_get_alarm_defs_docdb_dimension_key(self):
        defs = _get_alarm_defs("DocDB")
        for d in defs:
            assert d["dimension_key"] == "DBInstanceIdentifier", f"{d['metric']} dimension_key mismatch"

    def test_docdb_memory_less_than_threshold(self):
        defs = _get_alarm_defs("DocDB")
        mem_def = next(d for d in defs if d["metric"] == "FreeMemoryGB")
        assert mem_def["comparison"] == "LessThanThreshold"

    def test_docdb_memory_transform_threshold_exists(self):
        defs = _get_alarm_defs("DocDB")
        mem_def = next(d for d in defs if d["metric"] == "FreeMemoryGB")
        assert "transform_threshold" in mem_def
        assert mem_def["transform_threshold"](1) == 1073741824
        assert mem_def["transform_threshold"](2) == 2 * 1073741824

    def test_docdb_other_metrics_greater_than_threshold(self):
        defs = _get_alarm_defs("DocDB")
        for d in defs:
            if d["metric"] in ("CPU", "Connections"):
                assert d["comparison"] == "GreaterThanThreshold", f"{d['metric']} comparison mismatch"

    def test_docdb_excluded_metrics_not_in_hardcoded(self):
        defs = _get_alarm_defs("DocDB")
        metrics = {d["metric"] for d in defs}
        assert "FreeLocalStorageGB" not in metrics
        assert "ReadLatency" not in metrics
        assert "WriteLatency" not in metrics

    def test_hardcoded_metric_keys_docdb(self):
        assert _HARDCODED_METRIC_KEYS["DocDB"] == {"CPU", "FreeMemoryGB", "Connections"}

    def test_namespace_map_docdb(self):
        from common.alarm_manager import _NAMESPACE_MAP
        assert _NAMESPACE_MAP["DocDB"] == ["AWS/DocDB"]

    def test_dimension_key_map_docdb(self):
        from common.alarm_manager import _DIMENSION_KEY_MAP
        assert _DIMENSION_KEY_MAP["DocDB"] == "DBInstanceIdentifier"

    def test_supported_resource_types_includes_docdb(self):
        from common import SUPPORTED_RESOURCE_TYPES
        assert "DocDB" in SUPPORTED_RESOURCE_TYPES


# ──────────────────────────────────────────────
# 8개 신규 리소스 타입 알람 정의
# ──────────────────────────────────────────────

class TestLambdaAlarmDefs:
    """Lambda 알람 정의 검증. Validates: Requirements 1.1, 1.2, 9.1, 14.1"""

    def test_get_alarm_defs_lambda_count(self):
        defs = _get_alarm_defs("Lambda")
        assert len(defs) == 2

    def test_get_alarm_defs_lambda_metrics(self):
        defs = _get_alarm_defs("Lambda")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"Duration", "Errors"}

    def test_get_alarm_defs_lambda_namespace(self):
        defs = _get_alarm_defs("Lambda")
        for d in defs:
            assert d["namespace"] == "AWS/Lambda"

    def test_get_alarm_defs_lambda_dimension_key(self):
        defs = _get_alarm_defs("Lambda")
        for d in defs:
            assert d["dimension_key"] == "FunctionName"

    def test_lambda_duration_alarm_detail(self):
        defs = _get_alarm_defs("Lambda")
        dur = next(d for d in defs if d["metric"] == "Duration")
        assert dur["stat"] == "Average"
        assert dur["comparison"] == "GreaterThanThreshold"
        assert dur["period"] == 300

    def test_lambda_errors_alarm_detail(self):
        defs = _get_alarm_defs("Lambda")
        err = next(d for d in defs if d["metric"] == "Errors")
        assert err["stat"] == "Sum"
        assert err["comparison"] == "GreaterThanThreshold"


class TestVPNAlarmDefs:
    """VPN 알람 정의 검증. Validates: Requirements 2.1, 2.2, 2.3, 9.1"""

    def test_get_alarm_defs_vpn_count(self):
        defs = _get_alarm_defs("VPN")
        assert len(defs) == 1

    def test_get_alarm_defs_vpn_metrics(self):
        defs = _get_alarm_defs("VPN")
        assert defs[0]["metric"] == "TunnelState"

    def test_get_alarm_defs_vpn_namespace(self):
        defs = _get_alarm_defs("VPN")
        assert defs[0]["namespace"] == "AWS/VPN"

    def test_get_alarm_defs_vpn_dimension_key(self):
        defs = _get_alarm_defs("VPN")
        assert defs[0]["dimension_key"] == "VpnId"

    def test_vpn_treat_missing_data_breaching(self):
        defs = _get_alarm_defs("VPN")
        assert defs[0]["treat_missing_data"] == "breaching"

    def test_vpn_comparison_less_than(self):
        defs = _get_alarm_defs("VPN")
        assert defs[0]["comparison"] == "LessThanThreshold"
        assert defs[0]["stat"] == "Maximum"


class TestAPGWAlarmDefs:
    """APIGW 알람 정의 검증. Validates: Requirements 3-B.5, 3-B.6, 3-C.10, 3-C.11, 3-D.15, 3-D.16, 9.3"""

    def test_apigw_rest_count(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "REST"})
        assert len(defs) == 3

    def test_apigw_rest_metrics(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "REST"})
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ApiLatency", "Api4XXError", "Api5XXError"}

    def test_apigw_rest_dimension_key(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "REST"})
        for d in defs:
            assert d["dimension_key"] == "ApiName"
            assert d["namespace"] == "AWS/ApiGateway"

    def test_apigw_http_count(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "HTTP"})
        assert len(defs) == 3

    def test_apigw_http_metrics(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "HTTP"})
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ApiLatency", "Api4xx", "Api5xx"}

    def test_apigw_http_dimension_key(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "HTTP"})
        for d in defs:
            assert d["dimension_key"] == "ApiId"
            assert d["namespace"] == "AWS/ApiGateway"

    def test_apigw_websocket_count(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "WEBSOCKET"})
        assert len(defs) == 4

    def test_apigw_websocket_metrics(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "WEBSOCKET"})
        metrics = {d["metric"] for d in defs}
        assert metrics == {"WsConnectCount", "WsMessageCount", "WsIntegrationError", "WsExecutionError"}

    def test_apigw_websocket_dimension_key(self):
        defs = _get_alarm_defs("APIGW", {"_api_type": "WEBSOCKET"})
        for d in defs:
            assert d["dimension_key"] == "ApiId"
            assert d["namespace"] == "AWS/ApiGateway"

    def test_apigw_default_is_rest(self):
        defs = _get_alarm_defs("APIGW")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ApiLatency", "Api4XXError", "Api5XXError"}


class TestACMAlarmDefs:
    """ACM 알람 정의 검증. Validates: Requirements 4.1, 4.2, 9.1"""

    def test_get_alarm_defs_acm_count(self):
        defs = _get_alarm_defs("ACM")
        assert len(defs) == 1

    def test_get_alarm_defs_acm_metrics(self):
        defs = _get_alarm_defs("ACM")
        assert defs[0]["metric"] == "DaysToExpiry"

    def test_acm_namespace_and_dimension(self):
        defs = _get_alarm_defs("ACM")
        assert defs[0]["namespace"] == "AWS/CertificateManager"
        assert defs[0]["dimension_key"] == "CertificateArn"

    def test_acm_comparison_less_than(self):
        defs = _get_alarm_defs("ACM")
        assert defs[0]["comparison"] == "LessThanThreshold"

    def test_acm_period_daily(self):
        defs = _get_alarm_defs("ACM")
        assert defs[0]["period"] == 86400

    def test_acm_stat_minimum(self):
        defs = _get_alarm_defs("ACM")
        assert defs[0]["stat"] == "Minimum"


class TestBackupAlarmDefs:
    """Backup 알람 정의 검증. Validates: Requirements 5.1, 5.2, 9.1"""

    def test_get_alarm_defs_backup_count(self):
        defs = _get_alarm_defs("Backup")
        assert len(defs) == 2

    def test_get_alarm_defs_backup_metrics(self):
        defs = _get_alarm_defs("Backup")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"BackupJobsFailed", "BackupJobsAborted"}

    def test_backup_namespace_and_dimension(self):
        defs = _get_alarm_defs("Backup")
        for d in defs:
            assert d["namespace"] == "AWS/Backup"
            assert d["dimension_key"] == "BackupVaultName"


class TestMQAlarmDefs:
    """MQ 알람 정의 검증. Validates: Requirements 6.1, 6.2, 9.1"""

    def test_get_alarm_defs_mq_count(self):
        defs = _get_alarm_defs("MQ")
        assert len(defs) == 4

    def test_get_alarm_defs_mq_metrics(self):
        defs = _get_alarm_defs("MQ")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"MqCPU", "HeapUsage", "JobSchedulerStoreUsage", "StoreUsage"}

    def test_mq_namespace_and_dimension(self):
        defs = _get_alarm_defs("MQ")
        for d in defs:
            assert d["namespace"] == "AWS/AmazonMQ"
            assert d["dimension_key"] == "Broker"


class TestCLBAlarmDefs:
    """CLB 알람 정의 검증. Validates: Requirements 7.1, 7.2, 9.1"""

    def test_get_alarm_defs_clb_count(self):
        defs = _get_alarm_defs("CLB")
        assert len(defs) == 7

    def test_get_alarm_defs_clb_metrics(self):
        defs = _get_alarm_defs("CLB")
        metrics = {d["metric"] for d in defs}
        assert metrics == {
            "CLBUnHealthyHost", "CLB5XX", "CLB4XX",
            "CLBBackend5XX", "CLBBackend4XX",
            "SurgeQueueLength", "SpilloverCount",
        }

    def test_clb_namespace_and_dimension(self):
        defs = _get_alarm_defs("CLB")
        for d in defs:
            assert d["namespace"] == "AWS/ELB"
            assert d["dimension_key"] == "LoadBalancerName"

    def test_clb_period_60(self):
        defs = _get_alarm_defs("CLB")
        for d in defs:
            assert d["period"] == 60


class TestOpenSearchAlarmDefs:
    """OpenSearch 알람 정의 검증. Validates: Requirements 8.1, 8.2, 9.1"""

    def test_get_alarm_defs_opensearch_count(self):
        defs = _get_alarm_defs("OpenSearch")
        assert len(defs) == 8

    def test_get_alarm_defs_opensearch_metrics(self):
        defs = _get_alarm_defs("OpenSearch")
        metrics = {d["metric"] for d in defs}
        assert metrics == {
            "ClusterStatusRed", "ClusterStatusYellow",
            "OSFreeStorageSpace", "ClusterIndexWritesBlocked",
            "OsCPU", "JVMMemoryPressure",
            "MasterCPU", "MasterJVMMemoryPressure",
        }

    def test_opensearch_namespace_and_dimension(self):
        defs = _get_alarm_defs("OpenSearch")
        for d in defs:
            assert d["namespace"] == "AWS/ES"
            assert d["dimension_key"] == "DomainName"

    def test_opensearch_needs_client_id(self):
        defs = _get_alarm_defs("OpenSearch")
        for d in defs:
            assert d.get("needs_client_id") is True

    def test_opensearch_free_storage_less_than(self):
        defs = _get_alarm_defs("OpenSearch")
        fs = next(d for d in defs if d["metric"] == "OSFreeStorageSpace")
        assert fs["comparison"] == "LessThanThreshold"


# ──────────────────────────────────────────────
# 12개 Extended 리소스 타입 알람 정의
# ──────────────────────────────────────────────

class TestSQSAlarmDefs:
    """SQS 알람 정의 검증. Validates: Requirements 1.1, 1.2"""

    def test_get_alarm_defs_sqs_count(self):
        defs = _get_alarm_defs("SQS")
        assert len(defs) == 3

    def test_get_alarm_defs_sqs_metrics(self):
        defs = _get_alarm_defs("SQS")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"SQSMessagesVisible", "SQSOldestMessage", "SQSMessagesSent"}

    def test_sqs_namespace_and_dimension(self):
        defs = _get_alarm_defs("SQS")
        for d in defs:
            assert d["namespace"] == "AWS/SQS"
            assert d["dimension_key"] == "QueueName"

    def test_sqs_messages_visible_detail(self):
        defs = _get_alarm_defs("SQS")
        mv = next(d for d in defs if d["metric"] == "SQSMessagesVisible")
        assert mv["stat"] == "Average"
        assert mv["comparison"] == "GreaterThanThreshold"
        assert mv["metric_name"] == "ApproximateNumberOfMessagesVisible"

    def test_sqs_oldest_message_detail(self):
        defs = _get_alarm_defs("SQS")
        om = next(d for d in defs if d["metric"] == "SQSOldestMessage")
        assert om["stat"] == "Maximum"
        assert om["comparison"] == "GreaterThanThreshold"

    def test_sqs_messages_sent_detail(self):
        defs = _get_alarm_defs("SQS")
        ms = next(d for d in defs if d["metric"] == "SQSMessagesSent")
        assert ms["stat"] == "Sum"
        assert ms["comparison"] == "GreaterThanThreshold"


class TestECSAlarmDefs:
    """ECS 알람 정의 검증. Validates: Requirements 2-B.5, 2-B.6, 2-B.7, 13.3"""

    def test_get_alarm_defs_ecs_count(self):
        defs = _get_alarm_defs("ECS")
        assert len(defs) == 3

    def test_get_alarm_defs_ecs_metrics(self):
        defs = _get_alarm_defs("ECS")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"EcsCPU", "EcsMemory", "RunningTaskCount"}

    def test_ecs_namespace_and_dimension(self):
        defs = _get_alarm_defs("ECS")
        for d in defs:
            assert d["namespace"] == "AWS/ECS"
            assert d["dimension_key"] == "ServiceName"

    def test_ecs_running_task_count_less_than(self):
        defs = _get_alarm_defs("ECS")
        rtc = next(d for d in defs if d["metric"] == "RunningTaskCount")
        assert rtc["comparison"] == "LessThanThreshold"

    def test_ecs_launch_type_fargate_same_alarms(self):
        defs_fargate = _get_alarm_defs("ECS", {"_ecs_launch_type": "FARGATE"})
        defs_ec2 = _get_alarm_defs("ECS", {"_ecs_launch_type": "EC2"})
        assert {d["metric"] for d in defs_fargate} == {d["metric"] for d in defs_ec2}

    def test_ecs_launch_type_invariance(self):
        defs_default = _get_alarm_defs("ECS")
        defs_fargate = _get_alarm_defs("ECS", {"_ecs_launch_type": "FARGATE"})
        assert len(defs_default) == len(defs_fargate)


class TestMSKAlarmDefs:
    """MSK 알람 정의 검증. Validates: Requirements 3.1, 3.2, 3.3"""

    def test_get_alarm_defs_msk_count(self):
        defs = _get_alarm_defs("MSK")
        assert len(defs) == 4

    def test_get_alarm_defs_msk_metrics(self):
        defs = _get_alarm_defs("MSK")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"OffsetLag", "BytesInPerSec", "UnderReplicatedPartitions", "ActiveControllerCount"}

    def test_msk_namespace_and_dimension(self):
        defs = _get_alarm_defs("MSK")
        for d in defs:
            assert d["namespace"] == "AWS/Kafka"
            assert d["dimension_key"] == "Cluster Name"

    def test_msk_active_controller_count_breaching(self):
        defs = _get_alarm_defs("MSK")
        acc = next(d for d in defs if d["metric"] == "ActiveControllerCount")
        assert acc["treat_missing_data"] == "breaching"
        assert acc["comparison"] == "LessThanThreshold"

    def test_msk_other_metrics_no_breaching(self):
        defs = _get_alarm_defs("MSK")
        for d in defs:
            if d["metric"] != "ActiveControllerCount":
                assert d.get("treat_missing_data") is None


class TestDynamoDBAlarmDefs:
    """DynamoDB 알람 정의 검증. Validates: Requirements 4.1, 4.2"""

    def test_get_alarm_defs_dynamodb_count(self):
        defs = _get_alarm_defs("DynamoDB")
        assert len(defs) == 4

    def test_get_alarm_defs_dynamodb_metrics(self):
        defs = _get_alarm_defs("DynamoDB")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"DDBReadCapacity", "DDBWriteCapacity", "ThrottledRequests", "DDBSystemErrors"}

    def test_dynamodb_namespace_and_dimension(self):
        defs = _get_alarm_defs("DynamoDB")
        for d in defs:
            assert d["namespace"] == "AWS/DynamoDB"
            assert d["dimension_key"] == "TableName"


class TestCloudFrontAlarmDefs:
    """CloudFront 알람 정의 검증. Validates: Requirements 5.1, 5.2, 5.3"""

    def test_get_alarm_defs_cloudfront_count(self):
        defs = _get_alarm_defs("CloudFront")
        assert len(defs) == 4

    def test_get_alarm_defs_cloudfront_metrics(self):
        defs = _get_alarm_defs("CloudFront")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CF5xxErrorRate", "CF4xxErrorRate", "CFRequests", "CFBytesDownloaded"}

    def test_cloudfront_namespace_and_dimension(self):
        defs = _get_alarm_defs("CloudFront")
        for d in defs:
            assert d["namespace"] == "AWS/CloudFront"
            assert d["dimension_key"] == "DistributionId"

    def test_cloudfront_region_us_east_1(self):
        defs = _get_alarm_defs("CloudFront")
        for d in defs:
            assert d["region"] == "us-east-1"


class TestWAFAlarmDefs:
    """WAF 알람 정의 검증. Validates: Requirements 6.1, 6.2"""

    def test_get_alarm_defs_waf_count(self):
        defs = _get_alarm_defs("WAF")
        assert len(defs) == 3

    def test_get_alarm_defs_waf_metrics(self):
        defs = _get_alarm_defs("WAF")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"WAFBlockedRequests", "WAFAllowedRequests", "WAFCountedRequests"}

    def test_waf_namespace_and_dimension(self):
        defs = _get_alarm_defs("WAF")
        for d in defs:
            assert d["namespace"] == "AWS/WAFV2"
            assert d["dimension_key"] == "WebACL"


class TestRoute53AlarmDefs:
    """Route53 알람 정의 검증. Validates: Requirements 7.1, 7.2, 7.3, 7.4"""

    def test_get_alarm_defs_route53_count(self):
        defs = _get_alarm_defs("Route53")
        assert len(defs) == 1

    def test_route53_health_check_status(self):
        defs = _get_alarm_defs("Route53")
        assert defs[0]["metric"] == "HealthCheckStatus"

    def test_route53_namespace_and_dimension(self):
        defs = _get_alarm_defs("Route53")
        assert defs[0]["namespace"] == "AWS/Route53"
        assert defs[0]["dimension_key"] == "HealthCheckId"

    def test_route53_treat_missing_data_breaching(self):
        defs = _get_alarm_defs("Route53")
        assert defs[0]["treat_missing_data"] == "breaching"

    def test_route53_region_us_east_1(self):
        defs = _get_alarm_defs("Route53")
        assert defs[0]["region"] == "us-east-1"

    def test_route53_comparison_less_than(self):
        defs = _get_alarm_defs("Route53")
        assert defs[0]["comparison"] == "LessThanThreshold"
        assert defs[0]["stat"] == "Minimum"


class TestDXAlarmDefs:
    """DX 알람 정의 검증. Validates: Requirements 8.1, 8.2, 8.3"""

    def test_get_alarm_defs_dx_count(self):
        defs = _get_alarm_defs("DX")
        assert len(defs) == 1

    def test_dx_connection_state(self):
        defs = _get_alarm_defs("DX")
        assert defs[0]["metric"] == "ConnectionState"

    def test_dx_namespace_and_dimension(self):
        defs = _get_alarm_defs("DX")
        assert defs[0]["namespace"] == "AWS/DX"
        assert defs[0]["dimension_key"] == "ConnectionId"

    def test_dx_treat_missing_data_breaching(self):
        defs = _get_alarm_defs("DX")
        assert defs[0]["treat_missing_data"] == "breaching"

    def test_dx_comparison_less_than(self):
        defs = _get_alarm_defs("DX")
        assert defs[0]["comparison"] == "LessThanThreshold"
        assert defs[0]["stat"] == "Minimum"


class TestEFSAlarmDefs:
    """EFS 알람 정의 검증. Validates: Requirements 9.1, 9.2, 9.3"""

    def test_get_alarm_defs_efs_count(self):
        defs = _get_alarm_defs("EFS")
        assert len(defs) == 3

    def test_get_alarm_defs_efs_metrics(self):
        defs = _get_alarm_defs("EFS")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"BurstCreditBalance", "PercentIOLimit", "EFSClientConnections"}

    def test_efs_namespace_and_dimension(self):
        defs = _get_alarm_defs("EFS")
        for d in defs:
            assert d["namespace"] == "AWS/EFS"
            assert d["dimension_key"] == "FileSystemId"

    def test_efs_burst_credit_balance_less_than(self):
        defs = _get_alarm_defs("EFS")
        bcb = next(d for d in defs if d["metric"] == "BurstCreditBalance")
        assert bcb["comparison"] == "LessThanThreshold"


class TestS3AlarmDefs:
    """S3 알람 정의 검증. Validates: Requirements 10-A.1, 10-A.2, 10-A.3"""

    def test_get_alarm_defs_s3_count(self):
        defs = _get_alarm_defs("S3")
        assert len(defs) == 4

    def test_get_alarm_defs_s3_metrics(self):
        defs = _get_alarm_defs("S3")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"S34xxErrors", "S35xxErrors", "S3BucketSizeBytes", "S3NumberOfObjects"}

    def test_s3_namespace_and_dimension(self):
        defs = _get_alarm_defs("S3")
        for d in defs:
            assert d["namespace"] == "AWS/S3"
            assert d["dimension_key"] == "BucketName"

    def test_s3_bucket_size_needs_storage_type(self):
        defs = _get_alarm_defs("S3")
        bsb = next(d for d in defs if d["metric"] == "S3BucketSizeBytes")
        assert bsb["needs_storage_type"] is True
        assert bsb["period"] == 86400

    def test_s3_number_of_objects_needs_storage_type(self):
        defs = _get_alarm_defs("S3")
        noo = next(d for d in defs if d["metric"] == "S3NumberOfObjects")
        assert noo["needs_storage_type"] is True
        assert noo["period"] == 86400

    def test_s3_error_metrics_no_storage_type(self):
        defs = _get_alarm_defs("S3")
        for d in defs:
            if d["metric"] in ("S34xxErrors", "S35xxErrors"):
                assert d.get("needs_storage_type") is None or d.get("needs_storage_type") is False


class TestSageMakerAlarmDefs:
    """SageMaker 알람 정의 검증. Validates: Requirements 11-A.1, 11-A.2"""

    def test_get_alarm_defs_sagemaker_count(self):
        defs = _get_alarm_defs("SageMaker")
        assert len(defs) == 4

    def test_get_alarm_defs_sagemaker_metrics(self):
        defs = _get_alarm_defs("SageMaker")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"SMInvocations", "SMInvocationErrors", "SMModelLatency", "SMCPU"}

    def test_sagemaker_namespace_and_dimension(self):
        defs = _get_alarm_defs("SageMaker")
        for d in defs:
            assert d["namespace"] == "AWS/SageMaker"
            assert d["dimension_key"] == "EndpointName"

    def test_sagemaker_smcpu_avoids_collision(self):
        """SMCPU key avoids collision with EC2 CPU key."""
        defs = _get_alarm_defs("SageMaker")
        cpu = next(d for d in defs if d["metric"] == "SMCPU")
        assert cpu["metric_name"] == "CPUUtilization"
        assert cpu["metric"] == "SMCPU"


class TestSNSAlarmDefs:
    """SNS 알람 정의 검증. Validates: Requirements 12.1, 12.2"""

    def test_get_alarm_defs_sns_count(self):
        defs = _get_alarm_defs("SNS")
        assert len(defs) == 2

    def test_get_alarm_defs_sns_metrics(self):
        defs = _get_alarm_defs("SNS")
        metrics = {d["metric"] for d in defs}
        assert metrics == {"SNSNotificationsFailed", "SNSMessagesPublished"}

    def test_sns_namespace_and_dimension(self):
        defs = _get_alarm_defs("SNS")
        for d in defs:
            assert d["namespace"] == "AWS/SNS"
            assert d["dimension_key"] == "TopicName"


# ──────────────────────────────────────────────
# 8개 신규 리소스 타입 매핑 테이블 검증
# ──────────────────────────────────────────────

class TestNewResourceMappingTables:
    """8개 신규 리소스 타입 매핑 테이블 검증.
    Validates: Requirements 9.4, 9.5, 9.6, 9.7, 9.8
    """

    NEW_TYPES = [
        "Lambda", "VPN", "APIGW", "ACM",
        "Backup", "MQ", "CLB", "OpenSearch",
    ]

    def test_hardcoded_metric_keys_all_new_types(self):
        for rt in self.NEW_TYPES:
            assert rt in _HARDCODED_METRIC_KEYS, f"{rt} missing"

    def test_hardcoded_metric_keys_lambda(self):
        assert _HARDCODED_METRIC_KEYS["Lambda"] == {"Duration", "Errors"}

    def test_hardcoded_metric_keys_vpn(self):
        assert _HARDCODED_METRIC_KEYS["VPN"] == {"TunnelState"}

    def test_hardcoded_metric_keys_apigw(self):
        assert _HARDCODED_METRIC_KEYS["APIGW"] == {
            "ApiLatency", "Api4XXError", "Api5XXError",
            "Api4xx", "Api5xx",
            "WsConnectCount", "WsMessageCount",
            "WsIntegrationError", "WsExecutionError",
        }

    def test_hardcoded_metric_keys_acm(self):
        assert _HARDCODED_METRIC_KEYS["ACM"] == {"DaysToExpiry"}

    def test_hardcoded_metric_keys_backup(self):
        assert _HARDCODED_METRIC_KEYS["Backup"] == {"BackupJobsFailed", "BackupJobsAborted"}

    def test_hardcoded_metric_keys_mq(self):
        assert _HARDCODED_METRIC_KEYS["MQ"] == {
            "MqCPU", "HeapUsage", "JobSchedulerStoreUsage", "StoreUsage",
        }

    def test_hardcoded_metric_keys_clb(self):
        assert _HARDCODED_METRIC_KEYS["CLB"] == {
            "CLBUnHealthyHost", "CLB5XX", "CLB4XX",
            "CLBBackend5XX", "CLBBackend4XX",
            "SurgeQueueLength", "SpilloverCount",
        }

    def test_hardcoded_metric_keys_opensearch(self):
        assert _HARDCODED_METRIC_KEYS["OpenSearch"] == {
            "ClusterStatusRed", "ClusterStatusYellow",
            "OSFreeStorageSpace", "ClusterIndexWritesBlocked",
            "OsCPU", "JVMMemoryPressure",
            "MasterCPU", "MasterJVMMemoryPressure",
        }

    def test_namespace_map_all_new_types(self):
        from common.alarm_manager import _NAMESPACE_MAP
        expected = {
            "Lambda": ["AWS/Lambda"],
            "VPN": ["AWS/VPN"],
            "APIGW": ["AWS/ApiGateway"],
            "ACM": ["AWS/CertificateManager"],
            "Backup": ["AWS/Backup"],
            "MQ": ["AWS/AmazonMQ"],
            "CLB": ["AWS/ELB"],
            "OpenSearch": ["AWS/ES"],
        }
        for rt, ns in expected.items():
            assert _NAMESPACE_MAP[rt] == ns, f"{rt} namespace mismatch"

    def test_dimension_key_map_all_new_types(self):
        from common.alarm_manager import _DIMENSION_KEY_MAP
        expected = {
            "Lambda": "FunctionName",
            "VPN": "VpnId",
            "APIGW": "ApiName",
            "ACM": "CertificateArn",
            "Backup": "BackupVaultName",
            "MQ": "Broker",
            "CLB": "LoadBalancerName",
            "OpenSearch": "DomainName",
        }
        for rt, dk in expected.items():
            assert _DIMENSION_KEY_MAP[rt] == dk, f"{rt} dim key mismatch"

    def test_metric_display_all_new_metrics(self):
        new_metrics = {
            "Duration": ("Duration", ">", "ms"),
            "Errors": ("Errors", ">", ""),
            "TunnelState": ("TunnelState", "<", ""),
            "ApiLatency": ("Latency", ">", "ms"),
            "Api4XXError": ("4XXError", ">", ""),
            "Api5XXError": ("5XXError", ">", ""),
            "Api4xx": ("4xx", ">", ""),
            "Api5xx": ("5xx", ">", ""),
            "WsConnectCount": ("ConnectCount", ">", ""),
            "WsMessageCount": ("MessageCount", ">", ""),
            "WsIntegrationError": ("IntegrationError", ">", ""),
            "WsExecutionError": ("ExecutionError", ">", ""),
            "DaysToExpiry": ("DaysToExpiry", "<", "days"),
            "BackupJobsFailed": ("NumberOfBackupJobsFailed", ">", ""),
            "BackupJobsAborted": ("NumberOfBackupJobsAborted", ">", ""),
            "MqCPU": ("CpuUtilization", ">", "%"),
            "HeapUsage": ("HeapUsage", ">", "%"),
            "JobSchedulerStoreUsage": ("JobSchedulerStorePercentUsage", ">", "%"),
            "StoreUsage": ("StorePercentUsage", ">", "%"),
            "CLBUnHealthyHost": ("UnHealthyHostCount", ">", ""),
            "CLB5XX": ("HTTPCode_ELB_5XX", ">", ""),
            "CLB4XX": ("HTTPCode_ELB_4XX", ">", ""),
            "CLBBackend5XX": ("HTTPCode_Backend_5XX", ">", ""),
            "CLBBackend4XX": ("HTTPCode_Backend_4XX", ">", ""),
            "SurgeQueueLength": ("SurgeQueueLength", ">", ""),
            "SpilloverCount": ("SpilloverCount", ">", ""),
            "ClusterStatusRed": ("ClusterStatus.red", ">", ""),
            "ClusterStatusYellow": ("ClusterStatus.yellow", ">", ""),
            "OSFreeStorageSpace": ("FreeStorageSpace", "<", "MB"),
            "ClusterIndexWritesBlocked": ("ClusterIndexWritesBlocked", ">", ""),
            "OsCPU": ("CPUUtilization", ">", "%"),
            "JVMMemoryPressure": ("JVMMemoryPressure", ">", "%"),
            "MasterCPU": ("MasterCPUUtilization", ">", "%"),
            "MasterJVMMemoryPressure": ("MasterJVMMemoryPressure", ">", "%"),
        }
        for key, expected in new_metrics.items():
            assert _METRIC_DISPLAY[key] == expected, f"{key} display mismatch"

    def test_metric_name_to_key_new_mappings(self):
        roundtrips = {
            "Duration": "Duration",
            "Errors": "Errors",
            "TunnelState": "TunnelState",
            "Latency": "ApiLatency",
            "4XXError": "Api4XXError",
            "5XXError": "Api5XXError",
            "4xx": "Api4xx",
            "5xx": "Api5xx",
            "ConnectCount": "WsConnectCount",
            "MessageCount": "WsMessageCount",
            "IntegrationError": "WsIntegrationError",
            "ExecutionError": "WsExecutionError",
            "DaysToExpiry": "DaysToExpiry",
            "NumberOfBackupJobsFailed": "BackupJobsFailed",
            "NumberOfBackupJobsAborted": "BackupJobsAborted",
            "CpuUtilization": "MqCPU",
            "HeapUsage": "HeapUsage",
            "JobSchedulerStorePercentUsage": "JobSchedulerStoreUsage",
            "StorePercentUsage": "StoreUsage",
            "HTTPCode_ELB_5XX": "CLB5XX",
            "HTTPCode_ELB_4XX": "CLB4XX",
            "HTTPCode_Backend_5XX": "CLBBackend5XX",
            "HTTPCode_Backend_4XX": "CLBBackend4XX",
            "SurgeQueueLength": "SurgeQueueLength",
            "SpilloverCount": "SpilloverCount",
            "ClusterStatus.red": "ClusterStatusRed",
            "ClusterStatus.yellow": "ClusterStatusYellow",
            "ClusterIndexWritesBlocked": "ClusterIndexWritesBlocked",
            "MasterCPUUtilization": "MasterCPU",
            "MasterJVMMemoryPressure": "MasterJVMMemoryPressure",
        }
        for cw_name, expected_key in roundtrips.items():
            assert _metric_name_to_key(cw_name) == expected_key, f"{cw_name} → {expected_key} mismatch"


# ──────────────────────────────────────────────
# OpenSearch Compound Dimension (alarm def parts)
# ──────────────────────────────────────────────

class TestTreatMissingDataAndOpenSearchDimension:
    """OpenSearch DomainName+ClientId 디멘션 검증.
    Validates: Requirements 8.2, 8.5
    """

    def test_opensearch_dimensions_with_client_id(self):
        """OpenSearch 알람: _build_dimensions()가 DomainName + ClientId 2개 디멘션 반환."""
        alarm_def = _get_alarm_defs("OpenSearch")[0]
        tags = {"_client_id": "123456789012"}

        dims = _build_dimensions(alarm_def, "my-domain", "OpenSearch", tags)

        assert len(dims) == 2
        assert dims[0] == {"Name": "DomainName", "Value": "my-domain"}
        assert dims[1] == {"Name": "ClientId", "Value": "123456789012"}

    def test_opensearch_dimensions_without_client_id(self):
        """OpenSearch _client_id 누락 시 DomainName 1개 디멘션만 반환."""
        alarm_def = _get_alarm_defs("OpenSearch")[0]
        tags = {}

        dims = _build_dimensions(alarm_def, "my-domain", "OpenSearch", tags)

        assert len(dims) == 1
        assert dims[0] == {"Name": "DomainName", "Value": "my-domain"}


# ──────────────────────────────────────────────
# 12개 Extended 리소스 타입 매핑 테이블 검증
# ──────────────────────────────────────────────

class TestExtendedResourceMappingTables:
    """12개 Extended 리소스 타입 매핑 테이블 검증.
    Validates: Requirements 13.4, 13.5, 13.6, 13.7, 13.8
    """

    EXTENDED_TYPES = [
        "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
        "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
    ]

    def test_hardcoded_metric_keys_all_extended_types(self):
        for rt in self.EXTENDED_TYPES:
            assert rt in _HARDCODED_METRIC_KEYS, f"{rt} missing"

    def test_hardcoded_metric_keys_sqs(self):
        assert _HARDCODED_METRIC_KEYS["SQS"] == {"SQSMessagesVisible", "SQSOldestMessage", "SQSMessagesSent"}

    def test_hardcoded_metric_keys_ecs(self):
        assert _HARDCODED_METRIC_KEYS["ECS"] == {"EcsCPU", "EcsMemory", "RunningTaskCount"}

    def test_hardcoded_metric_keys_msk(self):
        assert _HARDCODED_METRIC_KEYS["MSK"] == {"OffsetLag", "BytesInPerSec", "UnderReplicatedPartitions", "ActiveControllerCount"}

    def test_hardcoded_metric_keys_dynamodb(self):
        assert _HARDCODED_METRIC_KEYS["DynamoDB"] == {"DDBReadCapacity", "DDBWriteCapacity", "ThrottledRequests", "DDBSystemErrors"}

    def test_hardcoded_metric_keys_cloudfront(self):
        assert _HARDCODED_METRIC_KEYS["CloudFront"] == {"CF5xxErrorRate", "CF4xxErrorRate", "CFRequests", "CFBytesDownloaded"}

    def test_hardcoded_metric_keys_waf(self):
        assert _HARDCODED_METRIC_KEYS["WAF"] == {"WAFBlockedRequests", "WAFAllowedRequests", "WAFCountedRequests"}

    def test_hardcoded_metric_keys_route53(self):
        assert _HARDCODED_METRIC_KEYS["Route53"] == {"HealthCheckStatus"}

    def test_hardcoded_metric_keys_dx(self):
        assert _HARDCODED_METRIC_KEYS["DX"] == {"ConnectionState"}

    def test_hardcoded_metric_keys_efs(self):
        assert _HARDCODED_METRIC_KEYS["EFS"] == {"BurstCreditBalance", "PercentIOLimit", "EFSClientConnections"}

    def test_hardcoded_metric_keys_s3(self):
        assert _HARDCODED_METRIC_KEYS["S3"] == {"S34xxErrors", "S35xxErrors", "S3BucketSizeBytes", "S3NumberOfObjects"}

    def test_hardcoded_metric_keys_sagemaker(self):
        assert _HARDCODED_METRIC_KEYS["SageMaker"] == {"SMInvocations", "SMInvocationErrors", "SMModelLatency", "SMCPU"}

    def test_hardcoded_metric_keys_sns(self):
        assert _HARDCODED_METRIC_KEYS["SNS"] == {"SNSNotificationsFailed", "SNSMessagesPublished"}

    def test_namespace_map_all_extended_types(self):
        from common.alarm_manager import _NAMESPACE_MAP
        expected = {
            "SQS": ["AWS/SQS"],
            "ECS": ["AWS/ECS"],
            "MSK": ["AWS/Kafka"],
            "DynamoDB": ["AWS/DynamoDB"],
            "CloudFront": ["AWS/CloudFront"],
            "WAF": ["AWS/WAFV2"],
            "Route53": ["AWS/Route53"],
            "DX": ["AWS/DX"],
            "EFS": ["AWS/EFS"],
            "S3": ["AWS/S3"],
            "SageMaker": ["AWS/SageMaker"],
            "SNS": ["AWS/SNS"],
        }
        for rt, ns in expected.items():
            assert _NAMESPACE_MAP[rt] == ns, f"{rt} namespace mismatch"

    def test_dimension_key_map_all_extended_types(self):
        from common.alarm_manager import _DIMENSION_KEY_MAP
        expected = {
            "SQS": "QueueName",
            "ECS": "ServiceName",
            "MSK": "Cluster Name",
            "DynamoDB": "TableName",
            "CloudFront": "DistributionId",
            "WAF": "WebACL",
            "Route53": "HealthCheckId",
            "DX": "ConnectionId",
            "EFS": "FileSystemId",
            "S3": "BucketName",
            "SageMaker": "EndpointName",
            "SNS": "TopicName",
        }
        for rt, dk in expected.items():
            assert _DIMENSION_KEY_MAP[rt] == dk, f"{rt} dim key mismatch"

    def test_metric_display_all_extended_metrics(self):
        extended_metrics = {
            "SQSMessagesVisible": ("ApproximateNumberOfMessagesVisible", ">", ""),
            "SQSOldestMessage": ("ApproximateAgeOfOldestMessage", ">", "s"),
            "SQSMessagesSent": ("NumberOfMessagesSent", ">", ""),
            "EcsCPU": ("CPUUtilization", ">", "%"),
            "EcsMemory": ("MemoryUtilization", ">", "%"),
            "RunningTaskCount": ("RunningTaskCount", "<", ""),
            "OffsetLag": ("SumOffsetLag", ">", ""),
            "BytesInPerSec": ("BytesInPerSec", ">", "B/s"),
            "UnderReplicatedPartitions": ("UnderReplicatedPartitions", ">", ""),
            "ActiveControllerCount": ("ActiveControllerCount", "<", ""),
            "DDBReadCapacity": ("ConsumedReadCapacityUnits", ">", ""),
            "DDBWriteCapacity": ("ConsumedWriteCapacityUnits", ">", ""),
            "ThrottledRequests": ("ThrottledRequests", ">", ""),
            "DDBSystemErrors": ("SystemErrors", ">", ""),
            "CF5xxErrorRate": ("5xxErrorRate", ">", "%"),
            "CF4xxErrorRate": ("4xxErrorRate", ">", "%"),
            "CFRequests": ("Requests", ">", ""),
            "CFBytesDownloaded": ("BytesDownloaded", ">", "B"),
            "WAFBlockedRequests": ("BlockedRequests", ">", ""),
            "WAFAllowedRequests": ("AllowedRequests", ">", ""),
            "WAFCountedRequests": ("CountedRequests", ">", ""),
            "HealthCheckStatus": ("HealthCheckStatus", "<", ""),
            "ConnectionState": ("ConnectionState", "<", ""),
            "BurstCreditBalance": ("BurstCreditBalance", "<", ""),
            "PercentIOLimit": ("PercentIOLimit", ">", "%"),
            "EFSClientConnections": ("ClientConnections", ">", ""),
            "S34xxErrors": ("4xxErrors", ">", ""),
            "S35xxErrors": ("5xxErrors", ">", ""),
            "S3BucketSizeBytes": ("BucketSizeBytes", ">", "B"),
            "S3NumberOfObjects": ("NumberOfObjects", ">", ""),
            "SMInvocations": ("Invocations", ">", ""),
            "SMInvocationErrors": ("InvocationErrors", ">", ""),
            "SMModelLatency": ("ModelLatency", ">", "μs"),
            "SMCPU": ("CPUUtilization", ">", "%"),
            "SNSNotificationsFailed": ("NumberOfNotificationsFailed", ">", ""),
            "SNSMessagesPublished": ("NumberOfMessagesPublished", ">", ""),
        }
        for key, expected in extended_metrics.items():
            assert _METRIC_DISPLAY[key] == expected, f"{key} display mismatch"

    def test_metric_name_to_key_extended_mappings(self):
        roundtrips = {
            "ApproximateNumberOfMessagesVisible": "SQSMessagesVisible",
            "ApproximateAgeOfOldestMessage": "SQSOldestMessage",
            "NumberOfMessagesSent": "SQSMessagesSent",
            "MemoryUtilization": "EcsMemory",
            "RunningTaskCount": "RunningTaskCount",
            "SumOffsetLag": "OffsetLag",
            "BytesInPerSec": "BytesInPerSec",
            "UnderReplicatedPartitions": "UnderReplicatedPartitions",
            "ActiveControllerCount": "ActiveControllerCount",
            "ConsumedReadCapacityUnits": "DDBReadCapacity",
            "ConsumedWriteCapacityUnits": "DDBWriteCapacity",
            "ThrottledRequests": "ThrottledRequests",
            "SystemErrors": "DDBSystemErrors",
            "5xxErrorRate": "CF5xxErrorRate",
            "4xxErrorRate": "CF4xxErrorRate",
            "Requests": "CFRequests",
            "BytesDownloaded": "CFBytesDownloaded",
            "BlockedRequests": "WAFBlockedRequests",
            "AllowedRequests": "WAFAllowedRequests",
            "CountedRequests": "WAFCountedRequests",
            "HealthCheckStatus": "HealthCheckStatus",
            "ConnectionState": "ConnectionState",
            "BurstCreditBalance": "BurstCreditBalance",
            "PercentIOLimit": "PercentIOLimit",
            "ClientConnections": "EFSClientConnections",
            "4xxErrors": "S34xxErrors",
            "5xxErrors": "S35xxErrors",
            "BucketSizeBytes": "S3BucketSizeBytes",
            "NumberOfObjects": "S3NumberOfObjects",
            "Invocations": "SMInvocations",
            "InvocationErrors": "SMInvocationErrors",
            "ModelLatency": "SMModelLatency",
            "NumberOfNotificationsFailed": "SNSNotificationsFailed",
            "NumberOfMessagesPublished": "SNSMessagesPublished",
        }
        for cw_name, expected_key in roundtrips.items():
            assert _metric_name_to_key(cw_name) == expected_key, f"{cw_name} → {expected_key} mismatch"
