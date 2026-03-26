"""
alarm_manager 단위 테스트

CloudWatch Alarm 자동 생성/삭제/동기화 기능 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from common import HARDCODED_DEFAULTS
from common.alarm_manager import (
    _alarm_name,
    _build_alarm_description,
    _build_dimensions,
    _create_dynamic_alarm,
    _extract_elb_dimension,
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
    _HARDCODED_METRIC_KEYS,
    _METRIC_DISPLAY,
    _metric_name_to_key,
    _parse_alarm_metadata,
    _parse_threshold_tags,
    _pretty_alarm_name,
    _resolve_free_memory_threshold,
    _resolve_metric_dimensions,
    _resolve_tg_namespace,
    _select_best_dimensions,
    _shorten_elb_resource_id,
    _find_alarms_for_resource,
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    import common.alarm_manager as am
    am._get_cw_client.cache_clear()
    yield
    am._get_cw_client.cache_clear()


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")


# ──────────────────────────────────────────────
# Helper 함수 테스트
# ──────────────────────────────────────────────

class TestHelpers:

    def test_legacy_alarm_name_format(self):
        assert _alarm_name("i-001", "CPU") == "i-001-CPU-prod"

    def test_legacy_alarm_name_with_different_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "dev")
        assert _alarm_name("db-001", "FreeMemoryGB") == "db-001-FreeMemoryGB-dev"

    def test_pretty_alarm_name_ec2_cpu(self):
        name = _pretty_alarm_name("EC2", "i-001", "my-server", "CPU", 80)
        assert name == "[EC2] my-server CPUUtilization >80% (i-001)"

    def test_pretty_alarm_name_no_name_tag(self):
        name = _pretty_alarm_name("EC2", "i-001", "", "Memory", 90)
        assert name == "[EC2] i-001 mem_used_percent >90% (i-001)"

    def test_pretty_alarm_name_disk_root(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-root", 85)
        assert name == "[EC2] srv disk_used_percent(/) >85% (i-001)"

    def test_pretty_alarm_name_disk_data(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "Disk-data", 90)
        assert name == "[EC2] srv disk_used_percent(/data) >90% (i-001)"

    def test_pretty_alarm_name_rds_free_memory(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "FreeMemoryGB", 2)
        assert name == "[RDS] my-db FreeableMemory <2GB (db-001)"

    def test_pretty_alarm_name_rds_connections(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "Connections", 100)
        assert name == "[RDS] my-db DatabaseConnections >100 (db-001)"

    def test_pretty_alarm_name_float_threshold(self):
        name = _pretty_alarm_name("EC2", "i-001", "srv", "CPU", 85.5)
        assert name == "[EC2] srv CPUUtilization >85.5% (i-001)"

    def test_pretty_alarm_name_always_within_255_chars(self):
        long_name = "a" * 256
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith("(i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_label_first(self):
        long_name = "my-very-long-server-name-" * 10  # 250 chars
        name = _pretty_alarm_name("EC2", "i-001", long_name, "CPU", 80)
        assert len(name) <= 255
        assert "CPUUtilization" in name  # display_metric preserved
        assert name.endswith("(i-001)")
        assert "..." in name

    def test_pretty_alarm_name_truncates_display_metric_when_label_insufficient(self):
        # Very long resource_id leaves little room
        long_id = "i-" + "a" * 200
        name = _pretty_alarm_name("EC2", long_id, "srv", "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"({long_id})")

    def test_pretty_alarm_name_preserves_resource_id_always(self):
        long_id = "i-" + "x" * 150
        long_name = "n" * 200
        name = _pretty_alarm_name("EC2", long_id, long_name, "CPU", 80)
        assert len(name) <= 255
        assert name.endswith(f"({long_id})")

    def test_pretty_alarm_name_short_inputs_unchanged(self):
        name = _pretty_alarm_name("RDS", "db-001", "my-db", "CPU", 80)
        assert name == "[RDS] my-db CPUUtilization >80% (db-001)"
        assert len(name) <= 255

    # ── Task 2.1: ALB/NLB/TG suffix에 Short_ID 적용 검증 ──

    def test_pretty_alarm_name_alb_suffix_short_id(self):
        """ALB ARN → suffix가 (my-alb/1234567890abcdef)로 끝나는지 검증.
        Validates: Requirements 2.1
        """
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        name = _pretty_alarm_name("ALB", alb_arn, "my-alb", "CPU", 80.0)
        assert name.endswith("(my-alb/1234567890abcdef)")

    def test_pretty_alarm_name_nlb_suffix_short_id(self):
        """NLB ARN → suffix가 (my-nlb/1234567890abcdef)로 끝나는지 검증.
        Validates: Requirements 2.1
        """
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/1234567890abcdef"
        name = _pretty_alarm_name("NLB", nlb_arn, "my-nlb", "CPU", 80.0)
        assert name.endswith("(my-nlb/1234567890abcdef)")

    def test_pretty_alarm_name_tg_suffix_short_id(self):
        """TG ARN → suffix가 (my-tg/1234567890abcdef)로 끝나는지 검증.
        Validates: Requirements 2.1
        """
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/1234567890abcdef"
        name = _pretty_alarm_name("TG", tg_arn, "my-tg", "CPU", 80.0)
        assert name.endswith("(my-tg/1234567890abcdef)")

    def test_pretty_alarm_name_ec2_suffix_unchanged(self):
        """EC2 resource_id → 기존 동작 유지, suffix가 (i-xxx)로 끝나는지 검증.
        Validates: Requirements 2.2
        """
        name = _pretty_alarm_name("EC2", "i-xxx", "my-ec2", "CPU", 80.0)
        assert name.endswith("(i-xxx)")

    def test_pretty_alarm_name_rds_suffix_unchanged(self):
        """RDS resource_id → 기존 동작 유지, suffix가 (db-test)로 끝나는지 검증.
        Validates: Requirements 2.2
        """
        name = _pretty_alarm_name("RDS", "db-test", "my-rds", "CPU", 80.0)
        assert name.endswith("(db-test)")

    def test_extract_elb_dimension_from_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        assert _extract_elb_dimension(arn) == "app/my-alb/abc123"

    def test_extract_elb_dimension_tg_arn(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        assert _extract_elb_dimension(arn) == "targetgroup/my-tg/abc123"

    def test_extract_elb_dimension_fallback(self):
        assert _extract_elb_dimension("not-an-arn") == "not-an-arn"

    def test_get_alarm_defs_ec2(self):
        defs = _get_alarm_defs("EC2")
        assert len(defs) == 4
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "Memory", "Disk", "StatusCheckFailed"}

    def test_get_alarm_defs_rds(self):
        defs = _get_alarm_defs("RDS")
        assert len(defs) == 6
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency"}

    def test_get_alarm_defs_elb(self):
        defs = _get_alarm_defs("ELB")
        assert defs == []

    def test_get_alarm_defs_unknown(self):
        assert _get_alarm_defs("UNKNOWN") == []

    # ── Task 3.1: ALB/NLB/TG 알람 정의 분리 검증 ──

    def test_get_alarm_defs_alb(self):
        """_get_alarm_defs('ALB') → RequestCount, ELB5XX, TargetResponseTime (AWS/ApplicationELB) 반환.
        Validates: Requirements 4.1
        """
        defs = _get_alarm_defs("ALB")
        assert len(defs) == 3
        metrics = {d["metric"] for d in defs}
        assert metrics == {"RequestCount", "ELB5XX", "TargetResponseTime"}
        for d in defs:
            assert d["namespace"] == "AWS/ApplicationELB"
            assert d["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_nlb(self):
        """_get_alarm_defs('NLB') → ProcessedBytes, ActiveFlowCount, NewFlowCount, TCPClientReset, TCPTargetReset (AWS/NetworkELB) 반환.
        Validates: Requirements 4.2, 2.1, 2.2, 2.3
        """
        defs = _get_alarm_defs("NLB")
        assert len(defs) == 5
        metrics = {d["metric"] for d in defs}
        assert metrics == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}
        for d in defs:
            assert d["namespace"] == "AWS/NetworkELB"
            assert d["dimension_key"] == "LoadBalancer"

    def test_get_alarm_defs_tg(self):
        """_get_alarm_defs('TG') → HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime 반환.
        Validates: Requirements 4.3, 5.1, 5.2
        """
        defs = _get_alarm_defs("TG")
        assert len(defs) == 4
        metrics = {d["metric"] for d in defs}
        assert metrics == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}
        for d in defs:
            assert d["dimension_key"] == "TargetGroup"

    def test_get_alarm_defs_elb_removed(self):
        """_get_alarm_defs('ELB') → 빈 리스트 반환 (제거됨).
        Validates: Requirements 7.2
        """
        defs = _get_alarm_defs("ELB")
        assert defs == []

    def test_hardcoded_metric_keys_alb_nlb_tg(self):
        """_HARDCODED_METRIC_KEYS에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.2
        """
        from common.alarm_manager import _HARDCODED_METRIC_KEYS
        assert "ALB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["ALB"] == {"RequestCount", "ELB5XX", "TargetResponseTime"}
        assert "NLB" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["NLB"] == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}
        assert "TG" in _HARDCODED_METRIC_KEYS
        assert _HARDCODED_METRIC_KEYS["TG"] == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}
        assert "ELB" not in _HARDCODED_METRIC_KEYS

    def test_namespace_map_alb_nlb_tg(self):
        """_NAMESPACE_MAP에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.3
        """
        from common.alarm_manager import _NAMESPACE_MAP
        assert _NAMESPACE_MAP["ALB"] == ["AWS/ApplicationELB"]
        assert _NAMESPACE_MAP["NLB"] == ["AWS/NetworkELB"]
        assert _NAMESPACE_MAP["TG"] == ["AWS/ApplicationELB", "AWS/NetworkELB"]
        assert "ELB" not in _NAMESPACE_MAP

    def test_dimension_key_map_alb_nlb_tg(self):
        """_DIMENSION_KEY_MAP에 ALB/NLB/TG 키 존재, ELB 키 제거 검증.
        Validates: Requirements 7.4
        """
        from common.alarm_manager import _DIMENSION_KEY_MAP
        assert _DIMENSION_KEY_MAP["ALB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["NLB"] == "LoadBalancer"
        assert _DIMENSION_KEY_MAP["TG"] == "TargetGroup"
        assert "ELB" not in _DIMENSION_KEY_MAP


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


# ──────────────────────────────────────────────
# RDS ReadLatency/WriteLatency 알람 정의 검증 (TDD Red)
# ──────────────────────────────────────────────

def test_rds_read_write_latency_alarm_def():
    """RDS ReadLatency/WriteLatency 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """
    # _get_alarm_defs("RDS") → 6개 (CPU, FreeMemoryGB, FreeStorageGB, Connections, ReadLatency, WriteLatency)
    defs = _get_alarm_defs("RDS")
    assert len(defs) == 6
    metrics = {d["metric"] for d in defs}
    assert "ReadLatency" in metrics
    assert "WriteLatency" in metrics

    # _HARDCODED_METRIC_KEYS["RDS"] 검증
    assert _HARDCODED_METRIC_KEYS["RDS"] == {
        "CPU", "FreeMemoryGB", "FreeStorageGB", "Connections",
        "ReadLatency", "WriteLatency",
    }

    # _METRIC_DISPLAY 매핑 검증
    assert _METRIC_DISPLAY["ReadLatency"] == ("ReadLatency", ">", "s")
    assert _METRIC_DISPLAY["WriteLatency"] == ("WriteLatency", ">", "s")

    # _metric_name_to_key 변환 검증
    assert _metric_name_to_key("ReadLatency") == "ReadLatency"
    assert _metric_name_to_key("WriteLatency") == "WriteLatency"

    # HARDCODED_DEFAULTS 기본 임계치 검증
    assert HARDCODED_DEFAULTS["ReadLatency"] == 0.02
    assert HARDCODED_DEFAULTS["WriteLatency"] == 0.02

    # ReadLatency 알람 정의 상세 검증
    rl_def = next(d for d in defs if d["metric"] == "ReadLatency")
    assert rl_def["stat"] == "Average"
    assert rl_def["comparison"] == "GreaterThanThreshold"
    assert rl_def["namespace"] == "AWS/RDS"
    assert rl_def["dimension_key"] == "DBInstanceIdentifier"

    # WriteLatency 알람 정의 상세 검증
    wl_def = next(d for d in defs if d["metric"] == "WriteLatency")
    assert wl_def["stat"] == "Average"
    assert wl_def["comparison"] == "GreaterThanThreshold"
    assert wl_def["namespace"] == "AWS/RDS"
    assert wl_def["dimension_key"] == "DBInstanceIdentifier"


# ──────────────────────────────────────────────
# ALB ELB5XX/TargetResponseTime 알람 정의 검증 (TDD Red)
# ──────────────────────────────────────────────

def test_alb_elb5xx_target_response_time_alarm_def():
    """ALB ELB5XX/TargetResponseTime 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 8.4
    """
    # _get_alarm_defs("ALB") → 3개 (RequestCount, ELB5XX, TargetResponseTime)
    defs = _get_alarm_defs("ALB")
    assert len(defs) == 3
    metrics = {d["metric"] for d in defs}
    assert "ELB5XX" in metrics
    assert "TargetResponseTime" in metrics

    # _HARDCODED_METRIC_KEYS["ALB"] 검증
    assert _HARDCODED_METRIC_KEYS["ALB"] == {"RequestCount", "ELB5XX", "TargetResponseTime"}

    # _METRIC_DISPLAY 매핑 검증
    assert _METRIC_DISPLAY["ELB5XX"] == ("HTTPCode_ELB_5XX_Count", ">", "")
    assert _METRIC_DISPLAY["TargetResponseTime"] == ("TargetResponseTime", ">", "s")

    # _metric_name_to_key 변환 검증
    assert _metric_name_to_key("HTTPCode_ELB_5XX_Count") == "ELB5XX"
    assert _metric_name_to_key("TargetResponseTime") == "TargetResponseTime"

    # HARDCODED_DEFAULTS 기본 임계치 검증
    assert HARDCODED_DEFAULTS["ELB5XX"] == 50.0
    assert HARDCODED_DEFAULTS["TargetResponseTime"] == 5.0

    # ELB5XX 알람 정의 상세 검증
    elb5xx_def = next(d for d in defs if d["metric"] == "ELB5XX")
    assert elb5xx_def["dimension_key"] == "LoadBalancer"
    assert elb5xx_def["stat"] == "Sum"
    assert elb5xx_def["namespace"] == "AWS/ApplicationELB"

    # TargetResponseTime 알람 정의 상세 검증
    trt_def = next(d for d in defs if d["metric"] == "TargetResponseTime")
    assert trt_def["dimension_key"] == "LoadBalancer"
    assert trt_def["stat"] == "Average"
    assert trt_def["namespace"] == "AWS/ApplicationELB"


# ──────────────────────────────────────────────
# NLB TCPClientReset/TCPTargetReset 알람 정의 검증 (TDD Red)
# ──────────────────────────────────────────────

def test_nlb_tcp_reset_alarm_def():
    """NLB TCPClientReset/TCPTargetReset 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    # _get_alarm_defs("NLB") → 5개
    defs = _get_alarm_defs("NLB")
    assert len(defs) == 5
    metrics = {d["metric"] for d in defs}
    assert metrics == {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}

    # _HARDCODED_METRIC_KEYS["NLB"] 검증
    assert _HARDCODED_METRIC_KEYS["NLB"] == {
        "ProcessedBytes", "ActiveFlowCount", "NewFlowCount",
        "TCPClientReset", "TCPTargetReset",
    }

    # _METRIC_DISPLAY 매핑 검증
    assert _METRIC_DISPLAY["TCPClientReset"] == ("TCP_Client_Reset_Count", ">", "")
    assert _METRIC_DISPLAY["TCPTargetReset"] == ("TCP_Target_Reset_Count", ">", "")

    # _metric_name_to_key 변환 검증
    assert _metric_name_to_key("TCP_Client_Reset_Count") == "TCPClientReset"
    assert _metric_name_to_key("TCP_Target_Reset_Count") == "TCPTargetReset"

    # HARDCODED_DEFAULTS 기본 임계치 검증
    assert HARDCODED_DEFAULTS["TCPClientReset"] == 100.0
    assert HARDCODED_DEFAULTS["TCPTargetReset"] == 100.0

    # TCPClientReset 알람 정의 상세 검증
    tcr_def = next(d for d in defs if d["metric"] == "TCPClientReset")
    assert tcr_def["dimension_key"] == "LoadBalancer"
    assert tcr_def["stat"] == "Sum"
    assert tcr_def["namespace"] == "AWS/NetworkELB"

    # TCPTargetReset 알람 정의 상세 검증
    ttr_def = next(d for d in defs if d["metric"] == "TCPTargetReset")
    assert ttr_def["dimension_key"] == "LoadBalancer"
    assert ttr_def["stat"] == "Sum"
    assert ttr_def["namespace"] == "AWS/NetworkELB"


# ──────────────────────────────────────────────
# TG RequestCountPerTarget/TGResponseTime 알람 정의 검증 (TDD Red)
# ──────────────────────────────────────────────

def test_tg_request_count_response_time_alarm_def():
    """TG RequestCountPerTarget/TGResponseTime 알람 정의가 올바르게 등록되어 있는지 검증.
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.7, 5.8, 5.9, 5.10
    """
    # _get_alarm_defs("TG") → 4개 (HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime)
    defs = _get_alarm_defs("TG")
    assert len(defs) == 4
    metrics = {d["metric"] for d in defs}
    assert metrics == {"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}

    # _HARDCODED_METRIC_KEYS["TG"] 검증
    assert _HARDCODED_METRIC_KEYS["TG"] == {
        "HealthyHostCount", "UnHealthyHostCount",
        "RequestCountPerTarget", "TGResponseTime",
    }

    # _METRIC_DISPLAY 매핑 검증
    assert _METRIC_DISPLAY["RequestCountPerTarget"] == ("RequestCountPerTarget", ">", "")
    assert _METRIC_DISPLAY["TGResponseTime"] == ("TargetResponseTime", ">", "s")

    # _metric_name_to_key 변환 검증
    assert _metric_name_to_key("RequestCountPerTarget") == "RequestCountPerTarget"

    # HARDCODED_DEFAULTS 기본 임계치 검증
    assert HARDCODED_DEFAULTS["RequestCountPerTarget"] == 1000.0
    assert HARDCODED_DEFAULTS["TGResponseTime"] == 5.0

    # RequestCountPerTarget 알람 정의 상세 검증
    rcpt_def = next(d for d in defs if d["metric"] == "RequestCountPerTarget")
    assert rcpt_def["dimension_key"] == "TargetGroup"
    assert rcpt_def["stat"] == "Sum"
    assert rcpt_def["namespace"] == "AWS/ApplicationELB"

    # TGResponseTime 알람 정의 상세 검증
    tgrt_def = next(d for d in defs if d["metric"] == "TGResponseTime")
    assert tgrt_def["dimension_key"] == "TargetGroup"
    assert tgrt_def["stat"] == "Average"
    assert tgrt_def["namespace"] == "AWS/ApplicationELB"


# ──────────────────────────────────────────────
# _build_dimensions / _resolve_tg_namespace 테스트
# ──────────────────────────────────────────────

class TestBuildDimensions:

    def test_tg_returns_compound_dimensions(self):
        """TG → TargetGroup + LoadBalancer 복합 디멘션."""
        alarm_def = _get_alarm_defs("TG")[0]
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def456"
        tags = {"_lb_arn": lb_arn}

        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)

        assert len(dims) == 2
        assert dims[0] == {"Name": "TargetGroup", "Value": "targetgroup/my-tg/abc123"}
        assert dims[1] == {"Name": "LoadBalancer", "Value": "app/my-alb/def456"}

    def test_tg_nlb_compound_dimensions(self):
        """NLB TG → TargetGroup + LoadBalancer 복합 디멘션."""
        alarm_def = _get_alarm_defs("TG")[0]
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        tags = {"_lb_arn": lb_arn, "_lb_type": "network"}

        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)

        assert len(dims) == 2
        assert dims[0]["Name"] == "TargetGroup"
        assert dims[1] == {"Name": "LoadBalancer", "Value": "net/my-nlb/def456"}

    def test_alb_returns_single_loadbalancer_dimension(self):
        """ALB → LoadBalancer 단일 디멘션."""
        alarm_def = _get_alarm_defs("ALB")[0]
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"

        dims = _build_dimensions(alarm_def, alb_arn, "ALB", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "LoadBalancer", "Value": "app/my-alb/abc"}

    def test_nlb_returns_single_loadbalancer_dimension(self):
        """NLB → LoadBalancer 단일 디멘션."""
        alarm_def = _get_alarm_defs("NLB")[0]
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/abc"

        dims = _build_dimensions(alarm_def, nlb_arn, "NLB", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "LoadBalancer", "Value": "net/my-nlb/abc"}

    def test_ec2_returns_instance_id_dimension(self):
        """EC2 → InstanceId 단일 디멘션."""
        alarm_def = _get_alarm_defs("EC2")[0]  # CPU

        dims = _build_dimensions(alarm_def, "i-001", "EC2", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "InstanceId", "Value": "i-001"}

    def test_rds_returns_db_instance_dimension(self):
        """RDS → DBInstanceIdentifier 단일 디멘션."""
        alarm_def = _get_alarm_defs("RDS")[0]  # CPU

        dims = _build_dimensions(alarm_def, "db-001", "RDS", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "DBInstanceIdentifier", "Value": "db-001"}

    def test_extra_dimensions_appended(self):
        """alarm_def의 extra_dimensions가 추가됨."""
        alarm_def = {
            "dimension_key": "InstanceId",
            "extra_dimensions": [{"Name": "path", "Value": "/"}],
        }

        dims = _build_dimensions(alarm_def, "i-001", "EC2", {})

        assert len(dims) == 2
        assert dims[1] == {"Name": "path", "Value": "/"}

    def test_tg_with_extra_dimensions(self):
        """TG 복합 디멘션 + extra_dimensions."""
        alarm_def = {
            "dimension_key": "TargetGroup",
            "extra_dimensions": [{"Name": "AvailabilityZone", "Value": "us-east-1a"}],
        }
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def"
        tags = {"_lb_arn": lb_arn}

        dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)

        assert len(dims) == 3
        assert dims[0]["Name"] == "TargetGroup"
        assert dims[1]["Name"] == "LoadBalancer"
        assert dims[2] == {"Name": "AvailabilityZone", "Value": "us-east-1a"}

    def test_tg_new_alarms_have_compound_dimensions(self):
        """RequestCountPerTarget/TGResponseTime도 TargetGroup + LoadBalancer 복합 디멘션 생성.
        Validates: Requirements 5.3, 5.4
        """
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        lb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/def456"
        tags = {"_lb_arn": lb_arn}

        for alarm_def in _get_alarm_defs("TG"):
            if alarm_def["metric"] in ("RequestCountPerTarget", "TGResponseTime"):
                dims = _build_dimensions(alarm_def, tg_arn, "TG", tags)
                assert len(dims) == 2, f"{alarm_def['metric']} should have 2 dimensions"
                assert dims[0] == {"Name": "TargetGroup", "Value": "targetgroup/my-tg/abc123"}
                assert dims[1] == {"Name": "LoadBalancer", "Value": "app/my-alb/def456"}


class TestResolveTgNamespace:

    def test_network_lb_type_returns_network_elb(self):
        """_lb_type == 'network' → AWS/NetworkELB."""
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": "network"}

        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/NetworkELB"

    def test_application_lb_type_returns_alarm_def_namespace(self):
        """_lb_type == 'application' → alarm_def['namespace']."""
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": "application"}

        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_missing_lb_type_returns_alarm_def_namespace(self):
        """_lb_type 없음 → alarm_def['namespace'] (기본값)."""
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {}

        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_empty_lb_type_returns_alarm_def_namespace(self):
        """_lb_type == '' → alarm_def['namespace']."""
        alarm_def = {"namespace": "AWS/ApplicationELB"}
        tags = {"_lb_type": ""}

        assert _resolve_tg_namespace(alarm_def, tags) == "AWS/ApplicationELB"

    def test_tg_new_alarms_network_lb_type_returns_network_elb(self):
        """RequestCountPerTarget/TGResponseTime with _lb_type=='network' → AWS/NetworkELB.
        Validates: Requirements 5.5, 5.6
        """
        tags = {"_lb_type": "network"}
        for alarm_def in _get_alarm_defs("TG"):
            if alarm_def["metric"] in ("RequestCountPerTarget", "TGResponseTime"):
                ns = _resolve_tg_namespace(alarm_def, tags)
                assert ns == "AWS/NetworkELB", (
                    f"{alarm_def['metric']} with network LB should use AWS/NetworkELB"
                )


# ──────────────────────────────────────────────
# create_alarms_for_resource
# ──────────────────────────────────────────────

class TestCreateAlarms:

    def _mock_cw_with_disk(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "xfs"},
                {"Name": "path", "Value": "/"},
            ]}
        ]}
        # _find_alarms_for_resource 용 paginator mock
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_ec2_creates_cpu_memory_disk_alarms(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert len(created) == 4
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        # 새 포맷 확인
        assert any("[EC2] my-server" in n for n in created)
        assert any("(i-001)" in n for n in created)
        assert mock_cw.put_metric_alarm.call_count == 4

    def test_ec2_custom_threshold_from_tag(self):
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        cpu_call = [c for c in calls if c.kwargs["MetricName"] == "CPUUtilization"][0]
        assert cpu_call.kwargs["Threshold"] == 90.0
        # 알람 이름에 90% 포함
        assert ">90%" in cpu_call.kwargs["AlarmName"]

    def test_rds_creates_six_alarms(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Name": "my-db"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", tags)

        assert len(created) == 6
        assert mock_cw.put_metric_alarm.call_count == 6

    def test_rds_free_memory_threshold_converted_to_bytes(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Threshold_FreeMemoryGB": "4"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("db-001", "RDS", tags)

        calls = mock_cw.put_metric_alarm.call_args_list
        free_mem_call = [c for c in calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert free_mem_call.kwargs["Threshold"] == 4 * 1024 * 1024 * 1024

    def test_alb_extracts_dimension_from_arn(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(arn, "ALB", {"Monitoring": "on"})

        assert len(created) == 3
        # All ALB alarms use LoadBalancer single dimension (no TargetGroup)
        for call in mock_cw.put_metric_alarm.call_args_list:
            dims = call.kwargs["Dimensions"]
            assert len(dims) == 1
            assert dims[0]["Name"] == "LoadBalancer"
            assert dims[0]["Value"] == "app/my-alb/abc"

    def test_sns_arn_set_as_alarm_action(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args_list[0].kwargs
        assert kwargs["AlarmActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]
        assert kwargs["OKActions"] == ["arn:aws:sns:us-east-1:123:alert-topic"]

    def test_no_sns_arn_empty_actions(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "")
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        kwargs = mock_cw.put_metric_alarm.call_args_list[0].kwargs
        assert kwargs["AlarmActions"] == []

    def test_client_error_logged_and_skipped(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "LimitExceeded", "Message": "too many"}}, "PutMetricAlarm"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        assert created == []

    def test_unknown_resource_type_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("x-001", "UNKNOWN", {})
        assert created == []

    def test_ec2_disk_alarm_has_extra_dimensions(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {})

        calls = mock_cw.put_metric_alarm.call_args_list
        disk_call = [c for c in calls if c.kwargs["MetricName"] == "disk_used_percent"][0]
        dims = disk_call.kwargs["Dimensions"]
        dim_names = {d["Name"] for d in dims}
        assert "InstanceId" in dim_names
        assert "path" in dim_names
        assert "fstype" in dim_names
        assert "device" in dim_names

    def test_ec2_no_name_tag_uses_resource_id(self):
        mock_cw = self._mock_cw_with_disk()
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", {})

        # Name 태그 없으면 resource_id가 label로 사용됨
        assert any("[EC2] i-001" in n for n in created)


# ──────────────────────────────────────────────
# delete_alarms_for_resource
# ──────────────────────────────────────────────

class TestDeleteAlarms:

    def test_find_alarms_deduplicates_legacy_and_new_format(self):
        """레거시와 새 포맷 검색 결과가 중복되지 않는지 확인."""
        mock_cw = MagicMock()
        # Same alarm found by both legacy prefix and new format prefix
        shared_alarm = {"AlarmName": "i-001-CPU-prod"}
        new_alarm = {"AlarmName": "[EC2] srv CPUUtilization >80% (i-001)"}
        mock_paginator = MagicMock()
        # Call 1 (legacy prefix=i-001): returns shared_alarm
        # Call 2 (new prefix=[EC2] ): returns shared_alarm + new_alarm
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": [shared_alarm]}],
            [{"MetricAlarms": [shared_alarm, new_alarm]}],
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        # shared_alarm should appear only once
        assert result.count("i-001-CPU-prod") == 1
        assert "[EC2] srv CPUUtilization >80% (i-001)" in result
        assert len(result) == 2

    def test_ec2_deletes_legacy_and_new_format(self):
        mock_cw = MagicMock()
        # paginator mock: 레거시 prefix 검색 + 새 포맷 전체 검색
        legacy_page = {"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
            {"AlarmName": "i-001-Memory-prod"},
        ]}
        new_page = {"MetricAlarms": [
            {"AlarmName": "[EC2] my-server CPUUtilization >80% (i-001)"},
            {"AlarmName": "[EC2] my-server mem_used_percent >80% (i-001)"},
        ]}
        mock_paginator = MagicMock()
        # 첫 번째 paginate: prefix 검색, 두 번째: 전체 검색
        mock_paginator.paginate.side_effect = [[legacy_page], [new_page]]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert len(deleted) == 4
        mock_cw.delete_alarms.assert_called_once()

    def test_no_alarms_returns_empty(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("x-001", "UNKNOWN")
        assert deleted == []

    def test_client_error_returns_empty(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": [
            {"AlarmName": "i-001-CPU-prod"},
        ]}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.delete_alarms.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFound", "Message": "nope"}}, "DeleteAlarms"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource("i-001", "EC2")

        assert deleted == []

    def test_find_alarms_alb_also_searches_elb_prefix(self):
        """resource_type='ALB'일 때 [ELB] prefix 알람도 검색되는지 확인."""
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        legacy_alarm = {"AlarmName": f"[ELB] my-alb RequestCount >5000 ({alb_arn})"}
        new_alarm = {"AlarmName": f"[ALB] my-alb RequestCount >5000 ({alb_arn})"}
        mock_paginator = MagicMock()
        # Call 1: legacy prefix (alb_arn) → empty
        # Call 2: [ALB] prefix → new_alarm
        # Call 3: [ELB] prefix → legacy_alarm
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],           # legacy prefix search
            [{"MetricAlarms": [new_alarm]}],   # [ALB] prefix search
            [{"MetricAlarms": [legacy_alarm]}], # [ELB] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert new_alarm["AlarmName"] in result
        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 2

    def test_find_alarms_nlb_also_searches_elb_prefix(self):
        """resource_type='NLB'일 때 [ELB] prefix 알람도 검색되는지 확인."""
        mock_cw = MagicMock()
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/my-nlb/def456"
        legacy_alarm = {"AlarmName": f"[ELB] my-nlb ProcessedBytes >1000 ({nlb_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],            # legacy prefix search
            [{"MetricAlarms": []}],            # [NLB] prefix search
            [{"MetricAlarms": [legacy_alarm]}], # [ELB] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(nlb_arn, "NLB")

        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 1

    def test_find_alarms_tg_also_searches_elb_prefix(self):
        """resource_type='TG'일 때 [ELB] prefix 알람도 검색되는지 확인.
        Validates: Requirements 2.4, 3.5
        """
        mock_cw = MagicMock()
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/my-tg/abc123"
        legacy_alarm = {"AlarmName": f"[ELB] my-tg HealthyHostCount <1 ({tg_arn})"}
        new_alarm = {"AlarmName": f"[TG] my-tg HealthyHostCount <1 ({tg_arn})"}
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],            # legacy prefix search
            [{"MetricAlarms": [new_alarm]}],   # [TG] prefix search
            [{"MetricAlarms": [legacy_alarm]}], # [ELB] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource(tg_arn, "TG")

        assert new_alarm["AlarmName"] in result
        assert legacy_alarm["AlarmName"] in result
        assert len(result) == 2

    def test_find_alarms_ec2_does_not_search_elb_prefix(self):
        """resource_type='EC2'일 때 [ELB] prefix를 추가 검색하지 않는지 확인."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            [{"MetricAlarms": []}],  # legacy prefix search
            [{"MetricAlarms": []}],  # [EC2] prefix search
        ]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _find_alarms_for_resource("i-001", "EC2")

        assert result == []
        # EC2는 legacy + [EC2] = 2번만 paginate 호출
        assert mock_paginator.paginate.call_count == 2


# ──────────────────────────────────────────────
# sync_alarms_for_resource
# ──────────────────────────────────────────────

class TestSyncAlarms:

    def test_missing_alarm_gets_created(self):
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[]):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        # 알람이 없으면 전체 생성
        assert len(result["created"]) > 0

    def test_matching_threshold_is_ok(self):
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
        ]

        def _make_desc(metric_key):
            meta = json.dumps({"metric_key": metric_key, "resource_id": "i-001", "resource_type": "EC2"}, separators=(",", ":"))
            return f"Auto-created | {meta}"

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": "StatusCheckFailed" if "StatusCheckFailed" in n else ("disk_used_percent" if "disk" in n else "CPUUtilization"),
                    "AlarmDescription": _make_desc(mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["ok"]) == 4
        assert result["created"] == []
        assert result["updated"] == []

    def test_mismatched_threshold_gets_updated(self):
        import json
        mock_cw = MagicMock()
        existing = [
            "[EC2] srv CPUUtilization >70% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
        ]

        def _make_desc(metric_key):
            meta = json.dumps({"metric_key": metric_key, "resource_id": "i-001", "resource_type": "EC2"}, separators=(",", ":"))
            return f"Auto-created | {meta}"

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 70.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": "disk_used_percent" if "disk" in n else "CPUUtilization",
                    "AlarmDescription": _make_desc(mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Threshold_CPU": "90"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert len(result["updated"]) > 0

    def test_legacy_elb_alarm_migrated_to_alb(self):
        """기존 [ELB] 알람이 threshold 불일치 시 [ALB] 알람으로 재생성."""
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        legacy_name = f"[ELB] my-alb RequestCount >5000 ({alb_arn})"

        # 레거시 알람: MetricName 기반 폴백으로 metric_key="RequestCount" 매칭
        # threshold 불일치 → updated → _recreate_alarm_by_name → 새 [ALB] prefix
        def describe_side_effect(**kwargs):
            return {"MetricAlarms": [{
                "AlarmName": legacy_name,
                "Threshold": 5000.0,
                "MetricName": "RequestCount",
                "AlarmDescription": "Legacy alarm without metadata",
                "Dimensions": [],
            }]}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator

        # Threshold_RequestCount=8000 태그로 threshold 불일치 유도
        tags = {"Monitoring": "on", "Name": "my-alb", "Threshold_RequestCount": "8000"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=[legacy_name]):
            result = sync_alarms_for_resource(alb_arn, "ALB", tags)

        # threshold 불일치 → updated
        assert legacy_name in result["updated"]
        # put_metric_alarm이 [ALB] prefix 알람 이름으로 호출되었는지 확인
        put_calls = mock_cw.put_metric_alarm.call_args_list
        assert len(put_calls) > 0
        recreated_name = put_calls[0].kwargs.get("AlarmName", "")
        assert recreated_name.startswith("[ALB] "), f"Expected [ALB] prefix, got: {recreated_name}"


# ──────────────────────────────────────────────
# AlarmDescription 메타데이터 테스트
# ──────────────────────────────────────────────

class TestAlarmMetadata:

    def test_build_alarm_description_includes_json(self):
        desc = _build_alarm_description("EC2", "i-001", "CPU", "Auto-created")
        assert "Auto-created" in desc
        assert '{"metric_key":"CPU"' in desc
        assert '"resource_id":"i-001"' in desc
        assert '"resource_type":"EC2"' in desc
        assert " | " in desc

    def test_build_alarm_description_max_1024_chars(self):
        long_prefix = "x" * 2000
        desc = _build_alarm_description("EC2", "i-001", "CPU", long_prefix)
        assert len(desc) <= 1024

    def test_parse_alarm_metadata_valid(self):
        desc = 'Auto-created | {"metric_key":"CPU","resource_id":"i-001","resource_type":"EC2"}'
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["metric_key"] == "CPU"
        assert meta["resource_id"] == "i-001"
        assert meta["resource_type"] == "EC2"

    def test_parse_alarm_metadata_legacy_no_json(self):
        desc = "Auto-created by AWS Monitoring Engine for EC2 i-001"
        meta = _parse_alarm_metadata(desc)
        assert meta is None

    def test_parse_alarm_metadata_empty(self):
        assert _parse_alarm_metadata("") is None
        assert _parse_alarm_metadata(None) is None

    def test_create_alarms_includes_json_in_description(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "xfs"},
                {"Name": "path", "Value": "/"},
            ]}
        ]}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource("i-001", "EC2", {"Name": "srv"})

        # 모든 put_metric_alarm 호출에 JSON 메타데이터가 포함되어야 함
        for call in mock_cw.put_metric_alarm.call_args_list:
            desc = call.kwargs["AlarmDescription"]
            meta = _parse_alarm_metadata(desc)
            assert meta is not None, f"Missing JSON metadata in: {desc}"
            assert meta["resource_id"] == "i-001"
            assert meta["resource_type"] == "EC2"
            assert "metric_key" in meta

    def test_roundtrip_build_and_parse(self):
        """build → parse 라운드트립 검증."""
        desc = _build_alarm_description("RDS", "db-001", "FreeMemoryGB", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["metric_key"] == "FreeMemoryGB"
        assert meta["resource_id"] == "db-001"
        assert meta["resource_type"] == "RDS"

    # ── Task 6.1: AlarmDescription에 Full_ARN 유지 검증 ──

    def test_alarm_description_preserves_full_arn_alb(self):
        """ALB ARN → build → parse 라운드트립 시 resource_id에 Full_ARN 유지.
        Validates: Requirements 4.1
        """
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        desc = _build_alarm_description("ALB", alb_arn, "RequestCount", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == alb_arn

    def test_alarm_description_preserves_full_arn_nlb(self):
        """NLB ARN → build → parse 라운드트립 시 resource_id에 Full_ARN 유지.
        Validates: Requirements 4.1
        """
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/abcdef1234567890"
        desc = _build_alarm_description("NLB", nlb_arn, "ProcessedBytes", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == nlb_arn

    def test_alarm_description_preserves_full_arn_tg(self):
        """TG ARN → build → parse 라운드트립 시 resource_id에 Full_ARN 유지.
        Validates: Requirements 4.1
        """
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/fedcba0987654321"
        desc = _build_alarm_description("TG", tg_arn, "HealthyHostCount", "Auto-created")
        meta = _parse_alarm_metadata(desc)
        assert meta is not None
        assert meta["resource_id"] == tg_arn


# ──────────────────────────────────────────────
# _parse_threshold_tags 테스트
# ──────────────────────────────────────────────

class TestParseThresholdTags:

    def test_extracts_dynamic_metric_for_ec2(self):
        """하드코딩 목록에 없는 메트릭을 추출."""
        tags = {"Threshold_NetworkIn": "1000000", "Threshold_CPU": "90"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "NetworkIn" in result
        assert result["NetworkIn"] == (1000000.0, "GreaterThanThreshold")
        # CPU는 하드코딩 목록에 있으므로 제외
        assert "CPU" not in result

    def test_extracts_dynamic_metric_for_rds(self):
        tags = {"Threshold_ReadLatency": "0.01", "Threshold_FreeMemoryGB": "4", "Threshold_CustomRDS": "50"}
        result = _parse_threshold_tags(tags, "RDS")
        # ReadLatency is now hardcoded in _HARDCODED_METRIC_KEYS["RDS"], so excluded from dynamic results
        assert "ReadLatency" not in result
        assert "FreeMemoryGB" not in result
        # Non-hardcoded metric should be included
        assert "CustomRDS" in result
        assert result["CustomRDS"] == (50.0, "GreaterThanThreshold")

    def test_skips_disk_prefix_tags(self):
        """Threshold_Disk_* 패턴은 기존 Disk 로직에서 처리하므로 제외."""
        tags = {"Threshold_Disk_root": "85", "Threshold_Disk_data": "90"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_non_numeric_value(self):
        tags = {"Threshold_CustomMetric": "not-a-number"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_zero_or_negative_value(self):
        tags = {"Threshold_CustomMetric": "0", "Threshold_Another": "-5"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_empty_metric_name(self):
        tags = {"Threshold_": "100"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_skips_tag_key_over_128_chars(self):
        long_key = "Threshold_" + "A" * 119  # 129 chars total
        tags = {long_key: "100"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_accepts_tag_key_at_128_chars(self):
        metric = "A" * 118  # Threshold_ (10) + 118 = 128
        tags = {f"Threshold_{metric}": "50"}
        result = _parse_threshold_tags(tags, "EC2")
        assert metric in result

    def test_no_threshold_tags_returns_empty(self):
        tags = {"Monitoring": "on", "Name": "my-server"}
        result = _parse_threshold_tags(tags, "EC2")
        assert result == {}

    def test_multiple_dynamic_metrics(self):
        tags = {
            "Threshold_NetworkIn": "1000",
            "Threshold_NetworkOut": "2000",
            "Threshold_DiskReadOps": "500",
        }
        result = _parse_threshold_tags(tags, "EC2")
        assert len(result) == 3

    def test_off_value_excluded_from_result(self):
        """Threshold_CustomMetric=off → 결과에서 제외.
        Validates: Requirements 2.1, 2.2
        """
        tags = {"Threshold_CustomMetric": "off"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert result == {}

    def test_off_value_case_insensitive(self):
        """Threshold_CustomMetric=OFF → 결과에서 제외 (대소문자 무관).
        Validates: Requirements 2.1, 2.2
        """
        tags = {"Threshold_CustomMetric": "OFF"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert result == {}

    def test_positive_number_included_alongside_off(self):
        """양의 숫자 태그는 정상 포함, off 태그는 제외.
        Validates: Requirements 2.1, 2.2
        """
        tags = {
            "Threshold_CustomMetric": "off",
            "Threshold_NetworkIn": "1000",
        }
        result = _parse_threshold_tags(tags, "EC2")
        assert "CustomMetric" not in result
        assert "NetworkIn" in result
        assert result["NetworkIn"] == (1000.0, "GreaterThanThreshold")

    def test_parse_threshold_tags_excludes_new_hardcoded_keys(self):
        """새 하드코딩 키가 _parse_threshold_tags 결과에서 제외되고,
        비하드코딩 키는 정상 반환되는지 검증.
        Validates: Requirements 6.1, 6.2, 6.3
        """
        # ALB: ELB5XX, TargetResponseTime 제외, CustomALB 포함
        tags = {"Threshold_ELB5XX": "100", "Threshold_TargetResponseTime": "10", "Threshold_CustomALB": "42"}
        result = _parse_threshold_tags(tags, "ALB")
        assert "ELB5XX" not in result
        assert "TargetResponseTime" not in result
        assert "CustomALB" in result
        assert result["CustomALB"] == (42.0, "GreaterThanThreshold")

        # NLB: TCPClientReset, TCPTargetReset 제외, CustomNLB 포함
        tags = {"Threshold_TCPClientReset": "200", "Threshold_TCPTargetReset": "300", "Threshold_CustomNLB": "55"}
        result = _parse_threshold_tags(tags, "NLB")
        assert "TCPClientReset" not in result
        assert "TCPTargetReset" not in result
        assert "CustomNLB" in result
        assert result["CustomNLB"] == (55.0, "GreaterThanThreshold")

        # EC2: StatusCheckFailed 제외, CustomEC2 포함
        tags = {"Threshold_StatusCheckFailed": "1", "Threshold_CustomEC2": "77"}
        result = _parse_threshold_tags(tags, "EC2")
        assert "StatusCheckFailed" not in result
        assert "CustomEC2" in result
        assert result["CustomEC2"] == (77.0, "GreaterThanThreshold")

        # RDS: ReadLatency, WriteLatency 제외, CustomRDS 포함
        tags = {"Threshold_ReadLatency": "0.05", "Threshold_WriteLatency": "0.05", "Threshold_CustomRDS": "33"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "ReadLatency" not in result
        assert "WriteLatency" not in result
        assert "CustomRDS" in result
        assert result["CustomRDS"] == (33.0, "GreaterThanThreshold")

        # TG: RequestCountPerTarget, TGResponseTime 제외, CustomTG 포함
        tags = {"Threshold_RequestCountPerTarget": "500", "Threshold_TGResponseTime": "3", "Threshold_CustomTG": "99"}
        result = _parse_threshold_tags(tags, "TG")
        assert "RequestCountPerTarget" not in result
        assert "TGResponseTime" not in result
        assert "CustomTG" in result
        assert result["CustomTG"] == (99.0, "GreaterThanThreshold")

    def test_lt_prefix_returns_less_than_threshold(self):
        """Threshold_LT_{MetricName} → LessThanThreshold 비교 연산자 반환.
        Validates: LT_ prefix for metrics where low values are dangerous.
        """
        tags = {"Threshold_LT_BufferCacheHitRatio": "95"}
        result = _parse_threshold_tags(tags, "RDS")
        assert "BufferCacheHitRatio" in result
        assert result["BufferCacheHitRatio"] == (95.0, "LessThanThreshold")


# ──────────────────────────────────────────────
# _resolve_metric_dimensions 테스트
# ──────────────────────────────────────────────

class TestResolveMetricDimensions:

    def test_resolves_ec2_metric(self):
        """EC2 메트릭의 네임스페이스/디멘션 해석."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is not None
        namespace, dims = result
        assert namespace in ("AWS/EC2", "CWAgent")
        assert any(d["Name"] == "InstanceId" for d in dims)

    def test_returns_none_when_metric_not_found(self):
        """메트릭이 없으면 None 반환."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NonExistent", "EC2")

        assert result is None

    def test_resolves_rds_metric(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "db-001"}]}
        ]}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("db-001", "ReadLatency", "RDS")

        assert result is not None
        namespace, dims = result
        assert namespace == "AWS/RDS"

    def test_elb_uses_arn_suffix_as_dimension(self):
        """ALB/NLB/TG는 ARN suffix를 디멘션 값으로 사용."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "LoadBalancer", "Value": "app/my-alb/abc"}]}
        ]}
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc"
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions(arn, "ProcessedBytes", "ALB")

        assert result is not None

    def test_client_error_returns_none(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "fail"}}, "ListMetrics"
        )
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = _resolve_metric_dimensions("i-001", "NetworkIn", "EC2")

        assert result is None


# ──────────────────────────────────────────────
# _create_dynamic_alarm 테스트
# ──────────────────────────────────────────────

class TestCreateDynamicAlarm:

    def test_creates_alarm_when_metric_resolved(self):
        """list_metrics로 해석된 메트릭에 대해 알람 생성."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NetworkIn", 1000000.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert "NetworkIn" in created[0]
        mock_cw.put_metric_alarm.assert_called_once()
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["Threshold"] == 1000000.0
        assert kwargs["MetricName"] == "NetworkIn"

    def test_skips_when_metric_not_resolved(self):
        """메트릭이 해석되지 않으면 알람 미생성."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NonExistent", 100.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert created == []
        mock_cw.put_metric_alarm.assert_not_called()

    def test_alarm_name_within_255_chars(self):
        """동적 알람 이름이 255자 이내."""
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        long_name = "x" * 200
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", long_name,
                "NetworkIn", 100.0, mock_cw, "", created,
            )

        assert len(created) == 1
        assert len(created[0]) <= 255

    def test_client_error_does_not_add_to_created(self):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        mock_cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "LimitExceeded", "Message": "too many"}},
            "PutMetricAlarm",
        )
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "srv",
                "NetworkIn", 100.0, mock_cw, "", created,
            )

        assert created == []

    # ── Task 3.1: 동적 알람 ALB/NLB/TG suffix에 Short_ID 적용 검증 ──

    def test_dynamic_alarm_alb_suffix_short_id(self):
        """ALB 동적 알람 생성 시 suffix가 Short_ID(name/hash)인지 검증.
        Validates: Requirements 2.4
        """
        mock_cw = MagicMock()
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "LoadBalancer", "Value": "app/my-alb/1234567890abcdef"}]}
        ]}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                alb_arn, "ALB", "my-alb",
                "CustomMetric", 100.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(my-alb/1234567890abcdef)")

    def test_dynamic_alarm_tg_suffix_short_id(self):
        """TG 동적 알람 생성 시 suffix가 Short_ID(name/hash)인지 검증.
        Validates: Requirements 2.4
        """
        mock_cw = MagicMock()
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abcdef1234567890"
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "TargetGroup", "Value": "targetgroup/my-tg/abcdef1234567890"}]}
        ]}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                tg_arn, "TG", "my-tg",
                "CustomMetric", 50.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(my-tg/abcdef1234567890)")

    def test_dynamic_alarm_ec2_suffix_unchanged(self):
        """EC2 동적 알람 suffix는 기존 동작 유지 (resource_id 그대로).
        Validates: Requirements 2.4
        """
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}
        created = []
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            _create_dynamic_alarm(
                "i-001", "EC2", "my-server",
                "NetworkIn", 1000.0, mock_cw,
                "arn:aws:sns:us-east-1:123:topic", created,
            )

        assert len(created) == 1
        assert created[0].endswith("(i-001)")


# ──────────────────────────────────────────────
# _shorten_elb_resource_id() 단위 테스트
# ──────────────────────────────────────────────

class TestShortenElbResourceId:
    """_shorten_elb_resource_id() 함수 단위 테스트.
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 5.3
    """

    def test_alb_arn_returns_name_hash(self):
        """ALB ARN → {name}/{hash} 반환."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "ALB") == "my-alb/1234567890abcdef"

    def test_nlb_arn_returns_name_hash(self):
        """NLB ARN → {name}/{hash} 반환."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "NLB") == "my-nlb/1234567890abcdef"

    def test_tg_arn_returns_name_hash(self):
        """TG ARN → {name}/{hash} 반환."""
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/1234567890abcdef"
        assert _shorten_elb_resource_id(arn, "TG") == "my-tg/1234567890abcdef"

    def test_ec2_instance_id_unchanged(self):
        """EC2 instance ID → 그대로 반환."""
        assert _shorten_elb_resource_id("i-0abc123def456789a", "EC2") == "i-0abc123def456789a"

    def test_rds_identifier_unchanged(self):
        """RDS identifier → 그대로 반환."""
        assert _shorten_elb_resource_id("db-test", "RDS") == "db-test"

    def test_non_arn_string_with_alb_type_unchanged(self):
        """ARN이 아닌 문자열 + resource_type=ALB → 그대로 반환 (방어적 처리)."""
        assert _shorten_elb_resource_id("some-random-string", "ALB") == "some-random-string"

    def test_empty_string_returns_empty(self):
        """빈 문자열 → 빈 문자열 반환."""
        assert _shorten_elb_resource_id("", "ALB") == ""

    def test_idempotent_alb_short_id(self):
        """이미 Short_ID 형태인 입력 → 동일 결과 (멱등성)."""
        short_id = "my-alb/1234567890abcdef"
        assert _shorten_elb_resource_id(short_id, "ALB") == short_id


# ──────────────────────────────────────────────
# Task 5.1: _find_alarms_for_resource() 레거시+새 포맷 호환 검색 (moto 기반)
# ──────────────────────────────────────────────

import boto3 as _boto3
from moto import mock_aws


def _put_alarm(cw, alarm_name: str) -> None:
    """moto CloudWatch에 더미 알람 생성 헬퍼."""
    cw.put_metric_alarm(
        AlarmName=alarm_name,
        Namespace="AWS/ApplicationELB",
        MetricName="RequestCount",
        Dimensions=[{"Name": "LoadBalancer", "Value": "app/my-alb/abc"}],
        Statistic="Sum",
        Period=60,
        EvaluationPeriods=1,
        Threshold=100,
        ComparisonOperator="GreaterThanThreshold",
    )


class TestFindAlarmsForResourceMoto:
    """_find_alarms_for_resource() 레거시+새 포맷 호환 검색 테스트 (moto 기반).
    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """

    @mock_aws
    def test_finds_short_id_suffix_alarms_only(self):
        """새 Short_ID suffix 알람만 존재 → 정상 검색.
        Validates: Requirements 3.1
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123def456"
        short_id = "my-alb/abc123def456"

        # 새 포맷 알람 (Short_ID suffix)
        _put_alarm(cw, f"[ALB] my-alb RequestCount >100 ({short_id})")
        _put_alarm(cw, f"[ALB] my-alb HTTPCode_ELB_5XX_Count >50 ({short_id})")

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert len(result) == 2
        assert all(name.endswith(f"({short_id})") for name in result)

    @mock_aws
    def test_finds_legacy_full_arn_suffix_alarms_only(self):
        """레거시 Full_ARN suffix 알람만 존재 → 정상 검색.
        Validates: Requirements 3.2
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        alb_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123def456"

        # 레거시 알람 (Full_ARN suffix)
        _put_alarm(cw, f"[ALB] my-alb RequestCount >100 ({alb_arn})")
        _put_alarm(cw, f"[ALB] my-alb HTTPCode_ELB_5XX_Count >50 ({alb_arn})")

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(alb_arn, "ALB")

        assert len(result) == 2
        assert all(name.endswith(f"({alb_arn})") for name in result)

    @mock_aws
    def test_finds_mixed_short_id_and_full_arn_no_duplicates(self):
        """혼재 상태 (Short_ID + Full_ARN suffix 알람 모두 존재) → 중복 없이 합산.
        Validates: Requirements 3.3
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123def456"
        short_id = "my-tg/abc123def456"

        # 레거시 알람 (Full_ARN suffix)
        _put_alarm(cw, f"[TG] my-tg HealthyHostCount <2 ({tg_arn})")
        # 새 포맷 알람 (Short_ID suffix)
        _put_alarm(cw, f"[TG] my-tg UnHealthyHostCount >0 ({short_id})")

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(tg_arn, "TG")

        assert len(result) == 2
        # 중복 없음
        assert len(set(result)) == 2
        names_str = " ".join(result)
        assert "HealthyHostCount" in names_str
        assert "UnHealthyHostCount" in names_str

    @mock_aws
    def test_ec2_search_unchanged(self):
        """EC2 → 기존 검색 로직 변경 없음.
        Validates: Requirements 3.4
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        instance_id = "i-0abc123def456789a"

        # 레거시 알람
        cw.put_metric_alarm(
            AlarmName=f"{instance_id}-CPU-prod",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )
        # 새 포맷 알람
        cw.put_metric_alarm(
            AlarmName=f"[EC2] my-server CPUUtilization >80% ({instance_id})",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(instance_id, "EC2")

        assert len(result) == 2
        assert f"{instance_id}-CPU-prod" in result
        assert f"[EC2] my-server CPUUtilization >80% ({instance_id})" in result

    @mock_aws
    def test_rds_search_unchanged(self):
        """RDS → 기존 검색 로직 변경 없음.
        Validates: Requirements 3.4
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-database"

        cw.put_metric_alarm(
            AlarmName=f"[RDS] my-db CPUUtilization >80% ({db_id})",
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id, "RDS")

        assert len(result) == 1
        assert f"[RDS] my-db CPUUtilization >80% ({db_id})" in result


# ──────────────────────────────────────────────
# _select_best_dimensions 테스트 (Task 2.1)
# ──────────────────────────────────────────────

class TestSelectBestDimensions:
    """_select_best_dimensions() 단위 테스트.
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """

    def test_primary_only_preferred(self):
        """Primary_Dimension_Key만 포함된 조합이 있으면 우선 선택.
        Validates: Requirements 1.1
        """
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        assert result == [{"Name": "InstanceId", "Value": "i-001"}]

    def test_no_primary_only_prefers_no_az_min_dims(self):
        """Primary_Dimension_Key만 포함된 조합이 없으면 AZ 미포함 + 최소 디멘션 선택.
        Validates: Requirements 1.2, 1.3, 1.4
        """
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda"},
                {"Name": "fstype", "Value": "xfs"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        # AZ 미포함 중 디멘션 수 최소 = 2개짜리
        assert result == [
            {"Name": "InstanceId", "Value": "i-001"},
            {"Name": "device", "Value": "xvda"},
        ]

    def test_all_have_az_selects_min_dims(self):
        """모든 조합에 AZ 포함 시 디멘션 수 최소 선택 (AZ 허용).
        Validates: Requirements 1.5
        """
        metrics = [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
                {"Name": "device", "Value": "xvda"},
            ]},
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "AvailabilityZone", "Value": "us-east-1a"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "InstanceId")
        # 모두 AZ 포함 → 디멘션 수 최소 (2개)
        assert result == [
            {"Name": "InstanceId", "Value": "i-001"},
            {"Name": "AvailabilityZone", "Value": "us-east-1a"},
        ]

    def test_empty_list_returns_empty(self):
        """빈 리스트 입력 시 빈 리스트 반환.
        Validates: Requirements 1.1
        """
        result = _select_best_dimensions([], "InstanceId")
        assert result == []


# ──────────────────────────────────────────────
# Task 5.1: create_alarms_for_resource() off 체크 테스트
# ──────────────────────────────────────────────

class TestCreateAlarmsOffCheck:
    """create_alarms_for_resource()에서 Threshold_*=off 태그 설정 시 해당 알람 스킵 검증.
    Validates: Requirements 3.1, 3.3, 4.1
    """

    def _mock_cw_with_disk(self):
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [
                {"Name": "InstanceId", "Value": "i-001"},
                {"Name": "device", "Value": "xvda1"},
                {"Name": "fstype", "Value": "xfs"},
                {"Name": "path", "Value": "/"},
            ]}
        ]}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        return mock_cw

    def test_cpu_off_skips_cpu_alarm(self):
        """Threshold_CPU=off → CPU 알람 생성 스킵, 나머지는 정상 생성.
        Validates: Requirements 3.1
        """
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server", "Threshold_CPU": "off"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        # CPU 알람이 생성되지 않아야 함
        assert not any("CPUUtilization" in n for n in created)
        # Memory, Disk, StatusCheckFailed는 정상 생성
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        assert len(created) == 3

    def test_disk_root_off_skips_root_disk_alarm(self):
        """Threshold_Disk_root=off → root Disk 알람 생성 스킵.
        Validates: Requirements 3.3
        """
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server", "Threshold_Disk_root": "off"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        # Disk 알람이 생성되지 않아야 함 (root만 있으므로)
        assert not any("disk_used_percent" in n for n in created)
        # CPU, Memory, StatusCheckFailed는 정상 생성
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)
        assert len(created) == 3

    def test_non_off_metrics_created_normally(self):
        """off 미설정 메트릭은 정상 생성.
        Validates: Requirements 3.1, 4.1
        """
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Name": "my-server"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        # 모든 4개 알람 정상 생성
        assert len(created) == 4
        assert any("CPUUtilization" in n for n in created)
        assert any("mem_used_percent" in n for n in created)
        assert any("disk_used_percent" in n for n in created)
        assert any("StatusCheckFailed" in n for n in created)

    def test_off_case_insensitive(self):
        """Threshold_CPU=OFF (대문자) → CPU 알람 생성 스킵.
        Validates: Requirements 3.1
        """
        mock_cw = self._mock_cw_with_disk()
        tags = {"Monitoring": "on", "Threshold_CPU": "OFF"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert len(created) == 3

    def test_multiple_off_metrics(self):
        """여러 메트릭 off → 해당 알람 모두 스킵.
        Validates: Requirements 3.1, 3.3
        """
        mock_cw = self._mock_cw_with_disk()
        tags = {
            "Monitoring": "on",
            "Threshold_CPU": "off",
            "Threshold_Memory": "off",
        }
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("i-001", "EC2", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert not any("mem_used_percent" in n for n in created)
        # Disk + StatusCheckFailed만 생성
        assert len(created) == 2

    def test_rds_off_metric_skipped(self):
        """RDS Threshold_CPU=off → CPU 알람 스킵, 나머지 5개 정상 생성.
        Validates: Requirements 3.1
        """
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        tags = {"Monitoring": "on", "Threshold_CPU": "off"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource("db-001", "RDS", tags)

        assert not any("CPUUtilization" in n for n in created)
        assert len(created) == 5  # 6 total - 1 CPU = 5


# ──────────────────────────────────────────────
# Task 6.1: sync 동적 알람 생성/삭제/업데이트 단위 테스트
# Validates: Requirements 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 7.3
# ──────────────────────────────────────────────

class TestSyncDynamicAlarms:
    """sync_alarms_for_resource()에서 동적 알람 생성/삭제/업데이트 검증."""

    @staticmethod
    def _make_desc(metric_key, resource_id="i-001", resource_type="EC2"):
        import json
        meta = json.dumps(
            {"metric_key": metric_key, "resource_id": resource_id,
             "resource_type": resource_type},
            separators=(",", ":"),
        )
        return f"Auto-created | {meta}"

    def test_new_dynamic_tag_creates_alarm(self):
        """새 동적 태그 추가 → created 목록에 포함.
        Validates: Requirements 5.1, 5.2
        """
        mock_cw = MagicMock()
        # 기존 하드코딩 알람 4개 (CPU, Memory, Disk_root, StatusCheckFailed)
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": n.split()[2] if len(n.split()) > 2 else "unknown",
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        # list_metrics for dynamic alarm creation
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}

        tags = {"Threshold_NetworkIn": "1000000"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert any("NetworkIn" in n for n in result["created"])

    def test_removed_dynamic_tag_deletes_alarm(self):
        """동적 태그 제거 → 기존 동적 알람 deleted 목록에 포함.
        Validates: Requirements 6.1, 6.2
        """
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn >1000000 (i-001)"
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        # 태그에 NetworkIn 없음 → 동적 알람 삭제 대상
        tags = {}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert "deleted" in result
        assert dynamic_alarm_name in result["deleted"]

    def test_dynamic_threshold_changed_updates_alarm(self):
        """동적 태그 임계치 변경 → updated 목록에 포함.
        Validates: Requirements 7.1, 7.3
        """
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn >1000000 (i-001)"
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.delete_alarms.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}
        ]}

        # 임계치 변경: 1000000 → 2000000
        tags = {"Threshold_NetworkIn": "2000000"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert dynamic_alarm_name in result["updated"]

    def test_dynamic_threshold_same_is_ok(self):
        """동적 태그 임계치 동일 → ok 목록에 포함.
        Validates: Requirements 7.2
        """
        mock_cw = MagicMock()
        dynamic_alarm_name = "[EC2] srv NetworkIn >1000000 (i-001)"
        existing = [
            "[EC2] srv CPUUtilization >80% (i-001)",
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
            dynamic_alarm_name,
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                elif "NetworkIn" in n:
                    mk, thr = "NetworkIn", 1000000.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        # 임계치 동일
        tags = {"Threshold_NetworkIn": "1000000"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert dynamic_alarm_name in result["ok"]


# ──────────────────────────────────────────────
# Task 6.2: sync 하드코딩 off 삭제 단위 테스트
# Validates: Requirements 3.2, 4.2, 4.3
# ──────────────────────────────────────────────

class TestSyncHardcodedOffDeletion:
    """sync_alarms_for_resource()에서 Threshold_*=off 시 기존 알람 삭제 검증."""

    @staticmethod
    def _make_desc(metric_key, resource_id="i-001", resource_type="EC2"):
        import json
        meta = json.dumps(
            {"metric_key": metric_key, "resource_id": resource_id,
             "resource_type": resource_type},
            separators=(",", ":"),
        )
        return f"Auto-created | {meta}"

    def test_off_tag_deletes_existing_hardcoded_alarm(self):
        """Threshold_CPU=off + 기존 CPU 알람 → deleted 목록에 포함.
        Validates: Requirements 3.2, 4.2
        """
        mock_cw = MagicMock()
        cpu_alarm_name = "[EC2] srv CPUUtilization >80% (i-001)"
        existing = [
            cpu_alarm_name,
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        tags = {"Threshold_CPU": "off"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert "deleted" in result
        assert cpu_alarm_name in result["deleted"]

    def test_off_deletion_logged(self):
        """off 삭제 시 로깅 검증.
        Validates: Requirements 4.3
        """
        import logging
        mock_cw = MagicMock()
        cpu_alarm_name = "[EC2] srv CPUUtilization >80% (i-001)"
        existing = [
            cpu_alarm_name,
            "[EC2] srv mem_used_percent >80% (i-001)",
            "[EC2] srv disk_used_percent(/) >80% (i-001)",
            "[EC2] srv StatusCheckFailed >0 (i-001)",
        ]

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                if "CPUUtilization" in n:
                    mk, thr = "CPU", 80.0
                elif "mem_used_percent" in n:
                    mk, thr = "Memory", 80.0
                elif "StatusCheckFailed" in n:
                    mk, thr = "StatusCheckFailed", 0.0
                else:
                    mk, thr = "Disk_root", 80.0
                alarms.append({
                    "AlarmName": n,
                    "Threshold": thr,
                    "MetricName": mk,
                    "AlarmDescription": self._make_desc(mk),
                    "Dimensions": [],
                })
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect
        mock_cw.delete_alarms.return_value = {}

        tags = {"Threshold_CPU": "off"}
        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing), \
             patch("common.alarm_manager.logger") as mock_logger:
            result = sync_alarms_for_resource("i-001", "EC2", tags)

        assert cpu_alarm_name in result["deleted"]
        # 로깅 호출 확인 (info 레벨)
        log_messages = [
            str(call) for call in mock_logger.info.call_args_list
        ]
        assert any("off" in msg.lower() or "delet" in msg.lower() for msg in log_messages)


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

    # 모든 정의가 AWS/RDS 네임스페이스, DBInstanceIdentifier 디멘션 사용
    for d in defs:
        assert d["namespace"] == "AWS/RDS"
        assert d["dimension_key"] == "DBInstanceIdentifier"
        assert d["period"] == 300
        assert d["evaluation_periods"] == 1

    # CPU: Average, GreaterThanThreshold
    cpu_def = next(d for d in defs if d["metric"] == "CPU")
    assert cpu_def["stat"] == "Average"
    assert cpu_def["comparison"] == "GreaterThanThreshold"
    assert cpu_def["metric_name"] == "CPUUtilization"

    # FreeMemoryGB: Average, LessThanThreshold, transform_threshold
    mem_def = next(d for d in defs if d["metric"] == "FreeMemoryGB")
    assert mem_def["stat"] == "Average"
    assert mem_def["comparison"] == "LessThanThreshold"
    assert mem_def["metric_name"] == "FreeableMemory"
    assert mem_def["transform_threshold"](2.0) == 2.0 * 1073741824

    # Connections: Average, GreaterThanThreshold
    conn_def = next(d for d in defs if d["metric"] == "Connections")
    assert conn_def["stat"] == "Average"
    assert conn_def["comparison"] == "GreaterThanThreshold"
    assert conn_def["metric_name"] == "DatabaseConnections"

    # FreeLocalStorageGB: Average, LessThanThreshold, transform_threshold
    storage_def = next(d for d in defs if d["metric"] == "FreeLocalStorageGB")
    assert storage_def["stat"] == "Average"
    assert storage_def["comparison"] == "LessThanThreshold"
    assert storage_def["metric_name"] == "FreeLocalStorage"
    assert storage_def["transform_threshold"](10.0) == 10737418240

    # ReplicaLag: Maximum, GreaterThanThreshold
    lag_def = next(d for d in defs if d["metric"] == "ReplicaLag")
    assert lag_def["stat"] == "Maximum"
    assert lag_def["comparison"] == "GreaterThanThreshold"
    assert lag_def["metric_name"] == "AuroraReplicaLagMaximum"


# ──────────────────────────────────────────────
# AuroraRDS 상수 매핑 검증 (Task 4.3 - TDD Red)
# ──────────────────────────────────────────────

def test_aurora_rds_constant_mappings():
    """AuroraRDS 상수 매핑 업데이트 검증.
    Validates: Requirements 5.3, 5.4
    """
    from common.alarm_manager import _NAMESPACE_MAP, _DIMENSION_KEY_MAP

    # _HARDCODED_METRIC_KEYS
    assert "AuroraRDS" in _HARDCODED_METRIC_KEYS
    assert _HARDCODED_METRIC_KEYS["AuroraRDS"] == {
        "CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag",
        "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity",
    }

    # _NAMESPACE_MAP
    assert _NAMESPACE_MAP["AuroraRDS"] == ["AWS/RDS"]

    # _DIMENSION_KEY_MAP
    assert _DIMENSION_KEY_MAP["AuroraRDS"] == "DBInstanceIdentifier"

    # _METRIC_DISPLAY: FreeLocalStorageGB, ReplicaLag
    assert _METRIC_DISPLAY["FreeLocalStorageGB"] == ("FreeLocalStorage", "<", "GB")
    assert _METRIC_DISPLAY["ReplicaLag"] == ("AuroraReplicaLagMaximum", ">", "μs")

    # _metric_name_to_key 변환
    assert _metric_name_to_key("FreeLocalStorage") == "FreeLocalStorageGB"
    assert _metric_name_to_key("AuroraReplicaLagMaximum") == "ReplicaLag"


# ──────────────────────────────────────────────
# Task 5.1: _find_alarms_for_resource() AuroraRDS 검색 검증
# ──────────────────────────────────────────────


class TestFindAlarmsForResourceAuroraRDS:
    """_find_alarms_for_resource() AuroraRDS 검색 호환 테스트.
    Validates: Requirements 8.1, 8.2
    """

    @mock_aws
    def test_aurora_rds_explicit_type_searches_with_correct_prefix_and_suffix(self):
        """resource_type='AuroraRDS' → prefix '[AuroraRDS] ' + suffix '({db_id})' 검색.
        Validates: Requirements 8.1
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-aurora-instance"

        # AuroraRDS 새 포맷 알람
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})",
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora FreeLocalStorage <10GB ({db_id})",
            Namespace="AWS/RDS",
            MetricName="FreeLocalStorage",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=10737418240,
            ComparisonOperator="LessThanThreshold",
        )
        # 다른 리소스의 알람 (검색에 포함되면 안 됨)
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] other-aurora CPUUtilization >80% (other-instance)",
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": "other-instance"}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id, "AuroraRDS")

        assert len(result) == 2
        assert all(name.endswith(f"({db_id})") for name in result)
        assert all(name.startswith("[AuroraRDS] ") for name in result)

    @mock_aws
    def test_default_fallback_includes_aurora_rds(self):
        """resource_type 미지정(default) → fallback 리스트에 'AuroraRDS' 포함하여 검색.
        Validates: Requirements 8.2
        """
        import common.alarm_manager as am
        am._get_cw_client.cache_clear()

        cw = _boto3.client("cloudwatch", region_name="us-east-1")
        db_id = "my-aurora-db"

        # AuroraRDS 알람
        cw.put_metric_alarm(
            AlarmName=f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})",
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=80,
            ComparisonOperator="GreaterThanThreshold",
        )

        # resource_type 미지정 → default fallback
        with patch("common.alarm_manager._get_cw_client", return_value=cw):
            result = _find_alarms_for_resource(db_id)

        assert len(result) >= 1
        assert f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})" in result


# ──────────────────────────────────────────────
# AuroraRDS 통합 시나리오 테스트 (Task 12.1)
# ──────────────────────────────────────────────

class TestAuroraRDSIntegration:
    """AuroraRDS 알람 생성 → sync → 삭제 end-to-end 통합 테스트.

    Validates: Requirements 6.2, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
    """

    @staticmethod
    def _make_mock_cw():
        """AuroraRDS 테스트용 mock CloudWatch 클라이언트 생성."""
        mock_cw = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]
        mock_cw.get_paginator.return_value = mock_paginator
        mock_cw.put_metric_alarm.return_value = {}
        mock_cw.delete_alarms.return_value = {}
        mock_cw.list_metrics.return_value = {"Metrics": []}
        return mock_cw

    def test_create_aurora_rds_creates_five_alarms(self):
        """sync_alarms_for_resource() 최초 호출 시 5개 AuroraRDS 알람 생성.

        Validates: Requirements 6.2, 10.1, 10.2, 10.3, 10.4, 10.5
        """
        mock_cw = self._make_mock_cw()
        tags = {
            "Monitoring": "on",
            "Name": "my-aurora",
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }
        db_id = "aurora-db-001"

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", tags)

        assert len(result["created"]) == 5
        created_names = result["created"]
        # 5개 메트릭 알람 이름에 올바른 prefix/suffix 포함
        assert all(n.startswith("[AuroraRDS] ") for n in created_names)
        assert all(n.endswith(f"({db_id})") for n in created_names)
        # 각 메트릭 display name 포함 검증
        assert any("CPUUtilization" in n for n in created_names)
        assert any("FreeableMemory" in n for n in created_names)
        assert any("DatabaseConnections" in n for n in created_names)
        assert any("FreeLocalStorage" in n for n in created_names)
        assert any("AuroraReplicaLagMaximum" in n for n in created_names)

    def test_sync_aurora_rds_matching_thresholds_ok(self):
        """기존 알람 임계치가 일치하면 ok 목록에 포함.

        Validates: Requirements 6.2
        """
        import json
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-002"

        existing = [
            f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory <2GB ({db_id})",
            f"[AuroraRDS] my-aurora DatabaseConnections >100 ({db_id})",
            f"[AuroraRDS] my-aurora FreeLocalStorage <10GB ({db_id})",
            f"[AuroraRDS] my-aurora AuroraReplicaLagMaximum >2000000μs ({db_id})",
        ]

        def _make_desc(metric_key):
            meta = json.dumps(
                {"metric_key": metric_key, "resource_id": db_id, "resource_type": "AuroraRDS"},
                separators=(",", ":"),
            )
            return f"Auto-created | {meta}"

        # transform_threshold: GB→bytes for FreeMemoryGB and FreeLocalStorageGB
        alarm_data = {
            "CPUUtilization": ("CPU", 80.0),
            "FreeableMemory": ("FreeMemoryGB", 2.0 * 1073741824),
            "DatabaseConnections": ("Connections", 100.0),
            "FreeLocalStorage": ("FreeLocalStorageGB", 10.0 * 1073741824),
            "AuroraReplicaLagMaximum": ("ReplicaLag", 2000000.0),
        }

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                for cw_metric, (mk, thr) in alarm_data.items():
                    if cw_metric in n:
                        alarms.append({
                            "AlarmName": n,
                            "Threshold": thr,
                            "MetricName": cw_metric,
                            "AlarmDescription": _make_desc(mk),
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        })
                        break
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", {
                "Name": "my-aurora",
                "_is_serverless_v2": "false",
                "_is_cluster_writer": "true",
                "_has_readers": "true",
            })

        assert len(result["ok"]) == 5
        assert result["created"] == []
        assert result["updated"] == []

    def test_resync_after_tag_change_updates_threshold(self):
        """태그 변경 후 re-sync 시 임계치 업데이트 검증.

        Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
        """
        import json
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-003"

        # 기존 알람: 기본 임계치로 생성됨
        existing = [
            f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory <2GB ({db_id})",
            f"[AuroraRDS] my-aurora DatabaseConnections >100 ({db_id})",
            f"[AuroraRDS] my-aurora FreeLocalStorage <10GB ({db_id})",
            f"[AuroraRDS] my-aurora AuroraReplicaLagMaximum >2000000μs ({db_id})",
        ]

        def _make_desc(metric_key):
            meta = json.dumps(
                {"metric_key": metric_key, "resource_id": db_id, "resource_type": "AuroraRDS"},
                separators=(",", ":"),
            )
            return f"Auto-created | {meta}"

        alarm_data = {
            "CPUUtilization": ("CPU", 80.0),
            "FreeableMemory": ("FreeMemoryGB", 2.0 * 1073741824),
            "DatabaseConnections": ("Connections", 100.0),
            "FreeLocalStorage": ("FreeLocalStorageGB", 10.0 * 1073741824),
            "AuroraReplicaLagMaximum": ("ReplicaLag", 2000000.0),
        }

        def describe_side_effect(**kwargs):
            names = kwargs.get("AlarmNames", [])
            alarms = []
            for n in names:
                for cw_metric, (mk, thr) in alarm_data.items():
                    if cw_metric in n:
                        alarms.append({
                            "AlarmName": n,
                            "Threshold": thr,
                            "MetricName": cw_metric,
                            "AlarmDescription": _make_desc(mk),
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        })
                        break
            return {"MetricAlarms": alarms}

        mock_cw.describe_alarms.side_effect = describe_side_effect

        # 태그 변경: 모든 5개 메트릭 임계치 오버라이드
        tags = {
            "Name": "my-aurora",
            "Threshold_CPU": "90",
            "Threshold_FreeMemoryGB": "4",
            "Threshold_Connections": "200",
            "Threshold_FreeLocalStorageGB": "20",
            "Threshold_ReplicaLag": "3000000",
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource(db_id, "AuroraRDS", tags)

        # 모든 5개 알람이 updated 목록에 포함
        assert len(result["updated"]) == 5

    def test_delete_aurora_rds_alarms(self):
        """AuroraRDS 알람 삭제 검증.

        Validates: Requirements 6.2
        """
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-004"
        alarm_names = [
            f"[AuroraRDS] my-aurora CPUUtilization >80% ({db_id})",
            f"[AuroraRDS] my-aurora FreeableMemory <2GB ({db_id})",
        ]

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"MetricAlarms": [{"AlarmName": n} for n in alarm_names]}
        ]
        mock_cw.get_paginator.return_value = mock_paginator

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            deleted = delete_alarms_for_resource(db_id, "AuroraRDS")

        assert len(deleted) == 2
        mock_cw.delete_alarms.assert_called_once()

    def test_create_aurora_rds_transform_threshold_applied(self):
        """FreeMemoryGB/FreeLocalStorageGB 알람 생성 시 transform_threshold(GB→bytes) 적용 검증.

        Validates: Requirements 10.2, 10.3
        """
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-005"
        tags = {
            "Monitoring": "on",
            "Name": "my-aurora",
            "Threshold_FreeMemoryGB": "4",
            "Threshold_FreeLocalStorageGB": "20",
        }

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource(db_id, "AuroraRDS", tags)

        put_calls = mock_cw.put_metric_alarm.call_args_list
        # FreeableMemory: 4 GB → 4 * 1073741824 bytes
        mem_call = [c for c in put_calls if c.kwargs["MetricName"] == "FreeableMemory"][0]
        assert mem_call.kwargs["Threshold"] == 4.0 * 1073741824
        # FreeLocalStorage: 20 GB → 20 * 1073741824 bytes
        storage_call = [c for c in put_calls if c.kwargs["MetricName"] == "FreeLocalStorage"][0]
        assert storage_call.kwargs["Threshold"] == 20.0 * 1073741824

    def test_create_aurora_rds_replica_lag_stat_and_comparison(self):
        """ReplicaLag 알람: stat=Maximum, comparison=GreaterThanThreshold 검증.

        Validates: Requirements 10.4
        """
        mock_cw = self._make_mock_cw()
        db_id = "aurora-db-006"
        tags = {
            "Monitoring": "on",
            "Name": "my-aurora",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
            "_is_serverless_v2": "false",
        }

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            create_alarms_for_resource(db_id, "AuroraRDS", tags)

        put_calls = mock_cw.put_metric_alarm.call_args_list
        lag_call = [c for c in put_calls if c.kwargs["MetricName"] == "AuroraReplicaLagMaximum"][0]
        assert lag_call.kwargs["Statistic"] == "Maximum"
        assert lag_call.kwargs["ComparisonOperator"] == "GreaterThanThreshold"
        assert lag_call.kwargs["Threshold"] == 2000000.0

    def test_dynamic_alarm_for_aurora_rds(self):
        """AuroraRDS 동적 알람(하드코딩 외 Threshold_* 태그) 생성 검증.

        Validates: Requirements 10.6
        """
        mock_cw = self._make_mock_cw()
        # list_metrics로 동적 메트릭 디멘션 해석 성공 시나리오
        mock_cw.list_metrics.return_value = {
            "Metrics": [{
                "Namespace": "AWS/RDS",
                "MetricName": "CommitLatency",
                "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "aurora-db-007"}],
            }]
        }
        db_id = "aurora-db-007"
        tags = {
            "Monitoring": "on",
            "Name": "my-aurora",
            "Threshold_CommitLatency": "500",
        }

        with patch("common.alarm_manager._get_cw_client", return_value=mock_cw):
            created = create_alarms_for_resource(db_id, "AuroraRDS", tags)

        # 5개 하드코딩 + 1개 동적 = 6개
        assert len(created) == 6
        assert any("CommitLatency" in n for n in created)


# ──────────────────────────────────────────────
# Task 4.1: _get_aurora_alarm_defs() 6개 변형 검증
# ──────────────────────────────────────────────

class TestAuroraAlarmVariantRouting:
    """Aurora 인스턴스 변형별 알람 라우팅 검증.
    Validates: Requirements 2.1, 2.2, 3.1, 3.2, 4.4, 7.1, 7.2, 7.3, 11.1, 11.2
    """

    def test_provisioned_writer_with_readers(self):
        """Provisioned Writer (w/ readers): CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReplicaLag."""
        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag"}

    def test_provisioned_writer_no_readers(self):
        """Provisioned Writer (no readers): CPU, FreeMemoryGB, Connections, FreeLocalStorageGB."""
        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "true",
            "_has_readers": "false",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB"}

    def test_provisioned_reader(self):
        """Provisioned Reader: CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReaderReplicaLag."""
        tags = {
            "_is_serverless_v2": "false",
            "_is_cluster_writer": "false",
            "_has_readers": "true",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReaderReplicaLag"}

    def test_serverless_v2_writer_with_readers(self):
        """Serverless v2 Writer (w/ readers): CPU, ACUUtilization, Connections, ReplicaLag."""
        tags = {
            "_is_serverless_v2": "true",
            "_is_cluster_writer": "true",
            "_has_readers": "true",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections", "ReplicaLag"}

    def test_serverless_v2_writer_no_readers(self):
        """Serverless v2 Writer (no readers): CPU, ACUUtilization, Connections."""
        tags = {
            "_is_serverless_v2": "true",
            "_is_cluster_writer": "true",
            "_has_readers": "false",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections"}

    def test_serverless_v2_reader(self):
        """Serverless v2 Reader: CPU, ACUUtilization, Connections, ReaderReplicaLag."""
        tags = {
            "_is_serverless_v2": "true",
            "_is_cluster_writer": "false",
            "_has_readers": "true",
        }
        defs = _get_alarm_defs("AuroraRDS", tags)
        metrics = {d["metric"] for d in defs}
        assert metrics == {"CPU", "ACUUtilization", "Connections", "ReaderReplicaLag"}

    def test_aurora_reader_replica_lag_alarm_def_schema(self):
        """_AURORA_READER_REPLICA_LAG 상수 스키마 검증."""
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
        """_AURORA_ACU_UTILIZATION 상수 스키마 검증."""
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
        """_AURORA_SERVERLESS_CAPACITY 상수 스키마 검증."""
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
        """resource_tags 없이 호출 시 기존 _AURORA_RDS_ALARMS 호환 (base + FreeLocalStorageGB + ReplicaLag)."""
        defs = _get_alarm_defs("AuroraRDS", {})
        metrics = {d["metric"] for d in defs}
        # 태그 없으면 _is_serverless_v2 != "true" → FreeLocalStorageGB 포함
        # _is_cluster_writer != "true" 이므로 ReaderReplicaLag 아님
        # _is_cluster_writer == "false" 도 아님 (키 없음) → 기존 호환: base만
        assert "CPU" in metrics
        assert "FreeMemoryGB" in metrics
        assert "Connections" in metrics


# ──────────────────────────────────────────────
# Task 4.3: 상수 매핑 업데이트 검증
# ──────────────────────────────────────────────

class TestAuroraConstantMappings:
    """Aurora 신규 메트릭 상수 매핑 검증.
    Validates: Requirements 3.5, 7.6, 12.3
    """

    def test_metric_display_reader_replica_lag(self):
        """_METRIC_DISPLAY에 ReaderReplicaLag 엔트리 존재."""
        assert "ReaderReplicaLag" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ReaderReplicaLag"] == ("AuroraReplicaLag", ">", "μs")

    def test_metric_display_acu_utilization(self):
        """_METRIC_DISPLAY에 ACUUtilization 엔트리 존재."""
        assert "ACUUtilization" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ACUUtilization"] == ("ACUUtilization", ">", "%")

    def test_metric_display_serverless_database_capacity(self):
        """_METRIC_DISPLAY에 ServerlessDatabaseCapacity 엔트리 존재."""
        assert "ServerlessDatabaseCapacity" in _METRIC_DISPLAY
        assert _METRIC_DISPLAY["ServerlessDatabaseCapacity"] == ("ServerlessDatabaseCapacity", ">", "ACU")

    def test_hardcoded_metric_keys_aurora_rds_8_keys(self):
        """_HARDCODED_METRIC_KEYS['AuroraRDS']에 8개 키 전체 포함."""
        expected = {
            "CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB",
            "ReplicaLag", "ReaderReplicaLag", "ACUUtilization", "ServerlessDatabaseCapacity",
        }
        assert _HARDCODED_METRIC_KEYS["AuroraRDS"] == expected

    def test_metric_name_to_key_aurora_replica_lag(self):
        """_metric_name_to_key('AuroraReplicaLag') → 'ReaderReplicaLag'."""
        assert _metric_name_to_key("AuroraReplicaLag") == "ReaderReplicaLag"

    def test_metric_name_to_key_acu_utilization(self):
        """_metric_name_to_key('ACUUtilization') → 'ACUUtilization'."""
        assert _metric_name_to_key("ACUUtilization") == "ACUUtilization"

    def test_metric_name_to_key_serverless_database_capacity(self):
        """_metric_name_to_key('ServerlessDatabaseCapacity') → 'ServerlessDatabaseCapacity'."""
        assert _metric_name_to_key("ServerlessDatabaseCapacity") == "ServerlessDatabaseCapacity"


# ──────────────────────────────────────────────
# Task 6.1: _resolve_free_memory_threshold() 검증
# ──────────────────────────────────────────────

class TestResolveFreeMemoryThreshold:
    """퍼센트 기반 FreeableMemory 임계치 해석 검증.
    Validates: Requirements 5.1, 5.2, 5.3, 5.5, 6.5
    """

    def test_pct_with_total_memory(self):
        """Threshold_FreeMemoryPct=20, _total_memory_bytes=16GiB → bytes 계산.
        Validates: Requirements 5.1, 5.2
        """
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "_total_memory_bytes": "17179869184",  # 16 GiB
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)  # 20% of 16GiB = 3.2GB
        assert cw_bytes == pytest.approx(3435973836.8)  # 0.2 * 17179869184

    def test_pct_takes_precedence_over_gb(self):
        """Threshold_FreeMemoryPct + Threshold_FreeMemoryGB 동시 → 퍼센트 우선.
        Validates: Requirements 5.3
        """
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "Threshold_FreeMemoryGB": "4",
            "_total_memory_bytes": "17179869184",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)  # 20% of 16GiB
        assert cw_bytes == pytest.approx(3435973836.8)

    def test_invalid_pct_falls_back_to_default_pct(self, caplog):
        """Threshold_FreeMemoryPct=150 (무효) + _total_memory_bytes 있음 → 기본 20% 적용.
        Validates: Requirements 5.5
        """
        tags = {
            "Threshold_FreeMemoryPct": "150",
            "Threshold_FreeMemoryGB": "4",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        # 무효 pct → 2단계 기본 20% 적용 (16GiB * 20% = 3.2GB)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)
        assert any("FreeMemoryPct" in msg for msg in caplog.messages)

    def test_missing_total_memory_falls_back_to_gb(self, caplog):
        """Threshold_FreeMemoryPct=20 + _total_memory_bytes 미존재 → GB 폴백 + warning.
        Validates: Requirements 6.5
        """
        tags = {
            "Threshold_FreeMemoryPct": "20",
            "Threshold_FreeMemoryGB": "4",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == 4
        assert cw_bytes == pytest.approx(4 * 1024 * 1024 * 1024)
        assert any("total_memory" in msg.lower() or "_total_memory_bytes" in msg for msg in caplog.messages)

    def test_no_pct_tag_uses_gb_logic(self):
        """Threshold_FreeMemoryPct 미존재 + _total_memory_bytes 있음 → 기본 20% 적용.
        Validates: Requirements 5.1 (negative case)
        """
        tags = {
            "Threshold_FreeMemoryGB": "3",
            "_total_memory_bytes": "17179869184",
        }
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_no_pct_no_gb_uses_hardcoded_default(self):
        """Threshold_FreeMemoryPct/GB 모두 미존재 + _total_memory_bytes 있음 → 기본 20% 적용."""
        tags = {"_total_memory_bytes": "17179869184"}
        display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        # 20% of 16GiB = 3.2GB
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_zero_invalid(self, caplog):
        """Threshold_FreeMemoryPct=0 (경계값, 무효) + _total_memory_bytes → 기본 20%."""
        tags = {
            "Threshold_FreeMemoryPct": "0",
            "Threshold_FreeMemoryGB": "2",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_100_invalid(self, caplog):
        """Threshold_FreeMemoryPct=100 (경계값, 무효) + _total_memory_bytes → 기본 20%."""
        tags = {
            "Threshold_FreeMemoryPct": "100",
            "Threshold_FreeMemoryGB": "2",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)

    def test_pct_non_numeric_falls_back(self, caplog):
        """Threshold_FreeMemoryPct='abc' (비숫자) + _total_memory_bytes → 기본 20%."""
        tags = {
            "Threshold_FreeMemoryPct": "abc",
            "Threshold_FreeMemoryGB": "3",
            "_total_memory_bytes": "17179869184",
        }
        import logging
        with caplog.at_level(logging.WARNING):
            display_gb, cw_bytes = _resolve_free_memory_threshold(tags)
        assert display_gb == pytest.approx(3.2)
        assert cw_bytes == pytest.approx(0.2 * 17179869184)
