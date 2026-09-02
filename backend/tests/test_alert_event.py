"""
알림 이벤트 정규화 (common/alert_event.py) 테스트

이 파서가 이벤트를 버리면 되돌릴 수 없다(R2-1). 그래서 "어떤 입력에도 예외를 던지지 않고
남길 수 있는 만큼 남긴다"를 가장 강하게 고정한다.

- EventBridge 실제 페이로드 형태(State Change / Configuration Change) 파싱
- 메타데이터 우선, 이름 폴백, 관리 대상 아님 — 셋 다 기록됨
- series_id가 MetricHistoryTable 규약과 동일 (Phase 4a 조인 전제)
- 망가진 입력에도 예외 없음
- to_item: 빈 필드 제외, TTL, GSI 키, 원본 보존
"""

import json
from datetime import datetime, timezone

from common.alert_event import (
    CONFIG_CHANGE,
    RETENTION_DAYS,
    STATE_CHANGE,
    UNKNOWN,
    AlertEvent,
    from_eventbridge,
    to_item,
)
from common.alarm_naming import _build_alarm_description

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
ALB_ARN = "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:loadbalancer/app/web/abc123"


def state_change_event(**over):
    """실제 EventBridge CloudWatch Alarm State Change 페이로드 형태."""
    ev = {
        "version": "0",
        "id": "aa11bb22-cc33-dd44-ee55-ff6677889900",
        "detail-type": "CloudWatch Alarm State Change",
        "source": "aws.cloudwatch",
        "account": "111122223333",
        "time": "2026-09-02T10:15:30Z",
        "region": "ap-northeast-2",
        "resources": ["arn:aws:cloudwatch:ap-northeast-2:111122223333:alarm:test"],
        "detail": {
            "alarmName": "[EC2] web-01 CPUUtilization > 80% (TagName: i-0abc)",
            "state": {"value": "ALARM", "reason": "Threshold Crossed", "timestamp": "..."},
            "previousState": {"value": "OK", "reason": "..."},
            "configuration": {
                "description": _build_alarm_description("EC2", "i-0abc", "CPUUtilization", "auto"),
                "metrics": [{"metricStat": {"metric": {"name": "CPUUtilization",
                                                       "namespace": "AWS/EC2"}}}],
            },
        },
    }
    ev.update(over)
    return ev


class TestStateChange:
    def test_parses_all_fields(self):
        ev = from_eventbridge(state_change_event(), customer_id="cust-1")
        assert ev.event_type == STATE_CHANGE
        assert ev.event_id == "aa11bb22-cc33-dd44-ee55-ff6677889900"
        assert ev.occurred_at == "2026-09-02T10:15:30Z"
        assert ev.account_id == "111122223333" and ev.region == "ap-northeast-2"
        assert ev.customer_id == "cust-1"
        assert ev.alarm_name.startswith("[EC2] web-01")
        assert ev.alarm_arn.endswith(":alarm:test")
        assert ev.state == "ALARM" and ev.previous_state == "OK"
        assert ev.state_reason == "Threshold Crossed"
        assert ev.parse_error == ""

    def test_resource_resolved_from_description_metadata(self):
        ev = from_eventbridge(state_change_event())
        assert ev.resource_id == "i-0abc"
        assert ev.resource_type == "EC2"
        assert ev.metric_key == "CPUUtilization"

    def test_series_id_matches_metric_history_convention(self):
        """MetricHistoryTable의 series_id와 같아야 Phase 4a 조인이 성립한다."""
        ev = from_eventbridge(state_change_event())
        assert ev.series_id == "111122223333#i-0abc#CPUUtilization"

    def test_alb_uses_full_arn_not_short_id(self):
        """이름 서픽스는 short ID지만 인벤토리·메트릭 이력은 Full ARN을 쓴다."""
        e = state_change_event()
        e["detail"]["alarmName"] = "[ALB] web HTTPCode_ELB_5XX_Count > 10 (TagName: web/abc123)"
        e["detail"]["configuration"]["description"] = _build_alarm_description(
            "ALB", ALB_ARN, "HTTPCode_ELB_5XX_Count", "auto")
        ev = from_eventbridge(e)
        assert ev.resource_id == ALB_ARN
        assert ev.series_id == f"111122223333#{ALB_ARN}#HTTPCode_ELB_5XX_Count"

    def test_falls_back_to_name_when_description_missing(self):
        e = state_change_event()
        e["detail"]["configuration"].pop("description")
        ev = from_eventbridge(e)
        assert ev.resource_id == "i-0abc" and ev.resource_type == "EC2"
        # metric_key는 메타데이터에 없으므로 configuration.metrics에서 온다
        assert ev.metric_key == "CPUUtilization"

    def test_firing_and_clearing_flags(self):
        firing = from_eventbridge(state_change_event())
        assert firing.is_firing is True and firing.is_clearing is False

        e = state_change_event()
        e["detail"]["state"]["value"] = "OK"
        e["detail"]["previousState"]["value"] = "ALARM"
        clearing = from_eventbridge(e)
        assert clearing.is_firing is False and clearing.is_clearing is True

    def test_insufficient_data_also_clears(self):
        e = state_change_event()
        e["detail"]["state"]["value"] = "INSUFFICIENT_DATA"
        e["detail"]["previousState"]["value"] = "ALARM"
        assert from_eventbridge(e).is_clearing is True

    def test_long_reason_is_truncated(self):
        e = state_change_event()
        e["detail"]["state"]["reason"] = "x" * 2000
        assert len(from_eventbridge(e).state_reason) == 500


class TestConfigChange:
    def test_parses_operation(self):
        e = state_change_event()
        e["detail-type"] = "CloudWatch Alarm Configuration Change"
        e["detail"]["operation"] = "delete"
        ev = from_eventbridge(e)
        assert ev.event_type == CONFIG_CHANGE and ev.operation == "delete"
        assert ev.resource_id == "i-0abc"   # 감사에 리소스가 필요하다


class TestUnmanagedAndMalformed:
    """이벤트를 버리면 되돌릴 수 없다 — 무엇이 와도 기록 가능한 형태로 나와야 한다."""

    def test_unmanaged_alarm_is_still_recorded(self):
        e = state_change_event()
        e["detail"]["alarmName"] = "customer-own-alarm-not-ours"
        e["detail"]["configuration"].pop("description")
        ev = from_eventbridge(e)
        assert ev.parse_error == "unmanaged alarm format"
        assert ev.resource_id == ""             # 해석 못 했지만
        assert ev.alarm_name == "customer-own-alarm-not-ours"   # 이름과
        assert ev.state == "ALARM"              # 상태는 남는다
        assert ev.raw == e                      # 원본도 남는다

    def test_empty_event(self):
        ev = from_eventbridge({})
        assert ev.event_type == UNKNOWN and ev.raw == {}

    def test_missing_detail(self):
        ev = from_eventbridge({"id": "x", "account": "1", "detail-type": "CloudWatch Alarm State Change"})
        assert ev.event_id == "x" and ev.state == ""

    def test_detail_is_wrong_type(self):
        ev = from_eventbridge({"id": "x", "detail": "not a dict"})
        assert ev.event_id == "x"
        assert ev.parse_error != ""             # 사유가 남고
        assert ev.raw["detail"] == "not a dict"  # 원본이 보존된다

    def test_non_dict_input_does_not_raise(self):
        for bad in (None, "string", 42, []):
            ev = from_eventbridge(bad)
            assert ev.parse_error == "event is not a dict"
            assert ev.raw  # 뭐라도 남는다

    def test_resources_empty_list(self):
        e = state_change_event()
        e["resources"] = []
        assert from_eventbridge(e).alarm_arn == ""


class TestToItem:
    def test_keys_and_ttl(self):
        ev = from_eventbridge(state_change_event(), customer_id="cust-1")
        item = to_item(ev, now=NOW)
        assert item["series_id"] == "111122223333#i-0abc#CPUUtilization"
        assert item["event_key"] == "2026-09-02T10:15:30Z#aa11bb22"
        assert item["customer_day"] == "cust-1#2026-09-02"
        expected_ttl = int(NOW.timestamp()) + RETENTION_DAYS * 86400
        assert abs(item["ttl"] - expected_ttl) < 60

    def test_empty_fields_are_omitted_but_keys_always_present(self):
        item = to_item(AlertEvent(), now=NOW)
        assert item["series_id"] == "##" and item["event_key"] == "#"
        assert item["suppressed"] is False          # 집계가 존재를 전제한다
        assert "state" not in item and "alarm_name" not in item

    def test_suppression_is_recorded(self):
        ev = from_eventbridge(state_change_event())
        ev.suppressed = True
        ev.suppression_reason = "auto_pause"
        ev.incident_id = "inc-123"
        item = to_item(ev, now=NOW)
        assert item["suppressed"] is True
        assert item["suppression_reason"] == "auto_pause"
        assert item["incident_id"] == "inc-123"

    def test_raw_is_preserved_as_compact_json(self):
        ev = from_eventbridge(state_change_event())
        item = to_item(ev, now=NOW)
        assert json.loads(item["raw"])["detail-type"] == "CloudWatch Alarm State Change"
        assert '", "' not in item["raw"]     # compact

    def test_raw_is_capped(self):
        ev = AlertEvent(raw={"big": "x" * 20000})
        assert len(to_item(ev, now=NOW)["raw"]) <= 8000

    def test_unserializable_raw_does_not_raise(self):
        ev = AlertEvent(raw={"obj": object()})
        assert to_item(ev, now=NOW)["raw"]

    def test_customer_day_falls_back_to_today_when_time_missing(self):
        ev = AlertEvent(customer_id="c1")
        assert to_item(ev, now=NOW)["customer_day"] == "c1#2026-09-02"
