"""고객사 기본 임계치 — 개별 태그 → 고객사 기본값 → 시스템 기본값."""

from unittest.mock import patch

from common import customer_thresholds as ct
from common.tag_resolver import get_threshold

ROWS = [
    {"scope_id": "customer_id:HOME", "metric_key": "EC2#CPUUtilization", "threshold_value": "85"},
    {"scope_id": "customer_id:HOME", "metric_key": "RDS#CPUUtilization", "threshold_value": "70"},
    {"scope_id": "customer_id:HOME", "metric_key": "CPU", "threshold_value": "90"},           # 옛 형식(타입 없음) — 무시
    {"scope_id": "resource_id:i-1", "metric_key": "CPUUtilization", "proposed_threshold": "70"},  # 재보정 제안 — 무시
    {"scope_id": "customer_id:HOME", "metric_key": "EC2#mem_used_percent", "threshold_value": "-1"},  # 잘못된 값
]


def test_parse_keeps_only_typed_customer_rows():
    assert ct.parse_items(ROWS) == {("HOME", "EC2"): {"CPUUtilization": 85.0}, ("HOME", "RDS"): {"CPUUtilization": 70.0}}


def test_resource_tag_wins_then_customer_then_system():
    defaults = {"CPUUtilization": 85.0}
    assert get_threshold(ct.apply({}, defaults), "CPUUtilization") == 85.0            # 고객사 기본값
    assert get_threshold(ct.apply({"Threshold_CPUUtilization": "95"}, defaults), "CPUUtilization") == 95.0
    assert get_threshold(ct.apply({}, {}), "CPUUtilization") == 80.0                   # 시스템 기본값


def test_legacy_tag_and_off_still_win():
    defaults = {"CPUUtilization": 85.0}
    merged = ct.apply({"Threshold_CPU": "60"}, defaults)
    assert "Threshold_CPUUtilization" not in merged, "레거시 이름의 개별값이 있으면 고객사 값을 끼우지 않는다"
    assert get_threshold(merged, "CPUUtilization") == 60.0
    assert ct.apply({"Threshold_CPUUtilization": "off"}, defaults)["Threshold_CPUUtilization"] == "off"


def test_apply_does_not_mutate_and_source_of():
    tags = {"Name": "web"}
    ct.apply(tags, {"CPUUtilization": 85.0})
    assert tags == {"Name": "web"}
    assert ct.source_of({}, {"CPUUtilization": 85}, "CPUUtilization") == "customer"
    assert ct.source_of({"Threshold_CPU": "1"}, {"CPUUtilization": 85}, "CPUUtilization") == "resource"
    assert ct.source_of({}, {}, "CPUUtilization") == "system"


def test_load_for_customer_filters_and_survives_errors():
    from botocore.exceptions import ClientError

    class T:
        def __init__(self, err=False):
            self.err = err

        def query(self, **kw):
            if self.err:
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "Query")
            return {"Items": ROWS}

    assert ct.load_for_customer(T(), "HOME") == {"EC2": {"CPUUtilization": 85.0}, "RDS": {"CPUUtilization": 70.0}}
    assert ct.load_for_customer(T(err=True), "HOME") == {}
    assert ct.load_for_customer(T(), "") == {}


def test_daily_monitor_uses_customer_defaults_for_tags():
    from daily_monitor import lambda_handler as dm
    with patch.object(dm, "_customer_defaults", {"EC2": {"CPUUtilization": 85.0}}):
        tags = dm._tags_with_defaults({"type": "EC2", "tags": {"Monitoring": "on"}})
        assert tags["Threshold_CPUUtilization"] == "85"
        assert "Threshold_CPUUtilization" not in dm._tags_with_defaults({"type": "RDS", "tags": {}})
