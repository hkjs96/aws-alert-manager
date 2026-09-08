"""
EC2 애플리케이션 상태 검사 지표(`StatusCheckFailed_Application`) 알람 — 옵트인.

AWS가 VPC 내 관리형 ENI로 앱 엔드포인트를 60초마다 검사하고 인스턴스 단위 0/1 지표를 낸다.
**검사를 연결하지 않은 인스턴스는 지표 자체가 없다** — 이 사실이 아래 두 규칙의 근거다.
1. 기본 생성하지 않는다(태그 옵트인). 안 그러면 전 인스턴스에 빈 알람이 하나씩 생긴다.
2. treat_missing_data는 notBreaching이다. breaching이면 검사 없는 인스턴스가 전부 알람이 된다.
설계: docs/specs/ec2-application-status-checks/design.md
"""

from unittest.mock import MagicMock, patch

import pytest

from common import HARDCODED_DEFAULTS
from common.alarm_registry import (
    APP_STATUS_METRIC_KEY,
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
    get_severity,
)

TAG = f"Threshold_{APP_STATUS_METRIC_KEY}"
BASE_TAGS = {"Monitoring": "on", "Name": "srv"}


def _defs(tags):
    return _get_alarm_defs("EC2", tags)


def _app_def(tags):
    return next((d for d in _defs(tags) if d["metric"] == APP_STATUS_METRIC_KEY), None)


class TestOptIn:
    def test_absent_tag_creates_no_definition(self):
        assert _app_def(BASE_TAGS) is None

    def test_tag_adds_the_definition(self):
        assert _app_def({**BASE_TAGS, TAG: "0"}) is not None

    def test_off_keeps_definition_so_existing_alarm_is_removed(self):
        """`off`는 정의를 남긴다 — 하위 경로가 생성을 건너뛰고 기존 알람을 지운다(다른 지표와 동일)."""
        from common.tag_resolver import is_threshold_off
        tags = {**BASE_TAGS, TAG: "off"}
        assert _app_def(tags) is not None
        assert is_threshold_off(tags, APP_STATUS_METRIC_KEY) is True

    def test_opt_in_does_not_disturb_the_other_ec2_alarms(self):
        without = [d["metric"] for d in _defs(BASE_TAGS)]
        with_tag = [d["metric"] for d in _defs({**BASE_TAGS, TAG: "0"})]
        assert with_tag == [*without, APP_STATUS_METRIC_KEY]
        assert "CPUUtilization" in without and "StatusCheckFailed" in without

    def test_no_tags_at_all_is_safe(self):
        assert _app_def({}) is None
        assert _app_def(None) is None


class TestDefinitionShape:
    @pytest.fixture
    def d(self):
        return _app_def({**BASE_TAGS, TAG: "0"})

    def test_missing_data_is_not_breaching(self, d):
        """검사 없는 인스턴스는 데이터가 없다 — breaching이면 전부 알람이 된다."""
        assert d["treat_missing_data"] == "notBreaching"

    def test_immediate_one_minute_evaluation(self, d):
        """디바운스는 AWS 검사(연속 2회 실패)에 이미 있다 — 여기서 또 늦추지 않는다."""
        assert d["period"] == 60
        assert d["evaluation_periods"] == 1
        assert d.get("datapoints_to_alarm", 1) == 1

    def test_binary_metric_shape(self, d):
        assert d["namespace"] == "AWS/EC2"
        assert d["metric_name"] == APP_STATUS_METRIC_KEY
        assert d["dimension_key"] == "InstanceId"
        assert (d["stat"], d["comparison"]) == ("Maximum", "GreaterThanThreshold")
        assert HARDCODED_DEFAULTS[APP_STATUS_METRIC_KEY] == 0.0

    def test_severity_is_sev1_and_exempt_from_suppression(self):
        """앱 무응답은 가용성 직결 — SEV-1은 알림 파이프라인에서 어떤 억제도 받지 않는다(R3-8)."""
        from common.alert_suppression import SuppressionPolicy
        assert get_severity(APP_STATUS_METRIC_KEY) == "SEV-1"
        assert get_severity(APP_STATUS_METRIC_KEY) in SuppressionPolicy().exempt_severities

    def test_sev1_keeps_immediate_evaluation_after_policy(self, d):
        """M-of-N 정책이 SEV-1을 건드리면 가용성 감지가 늦어진다."""
        assert d["evaluation_periods"] == 1


class TestNoDuplicateDynamicAlarm:
    def test_metric_is_hardcoded_so_the_tag_does_not_also_make_a_dynamic_alarm(self):
        assert APP_STATUS_METRIC_KEY in _get_hardcoded_metric_keys("EC2", {**BASE_TAGS, TAG: "0"})

    def test_threshold_tag_is_filtered_from_dynamic_parsing(self):
        from common.alarm_manager import _parse_threshold_tags
        dynamic = _parse_threshold_tags({**BASE_TAGS, TAG: "0"}, "EC2")
        assert APP_STATUS_METRIC_KEY not in dynamic


class TestCreationPath:
    """실제 생성까지 — 태그를 켠 인스턴스에만 알람이 만들어지고 등급 태그가 붙는다."""

    @staticmethod
    def _create(tags):
        from common.alarm_manager import create_alarms_for_resource
        cw = MagicMock()
        cw.meta.region_name = "us-east-1"
        cw.list_tags_for_resource.return_value = {"Tags": []}
        with patch("common.alarm_manager._find_alarms_for_resource", return_value=[]), \
             patch("common.alarm_manager._delete_all_alarms_for_resource", return_value=[]), \
             patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"), \
             patch("common.alarm_builder._get_sns_alert_arn", return_value=""), \
             patch("common._clients._get_cw_client", return_value=cw):
            create_alarms_for_resource("i-001", "EC2", tags, cw=cw)
        return {c.kwargs["AlarmName"]: c.kwargs for c in cw.put_metric_alarm.call_args_list}, cw

    def test_opted_in_instance_gets_the_alarm(self):
        puts, cw = self._create({**BASE_TAGS, TAG: "0"})
        name = next((n for n in puts if APP_STATUS_METRIC_KEY in n), None)
        assert name, f"알람이 만들어지지 않았다: {list(puts)}"
        kw = puts[name]
        assert kw["MetricName"] == APP_STATUS_METRIC_KEY
        assert kw["TreatMissingData"] == "notBreaching"
        assert kw["Threshold"] == 0.0
        assert kw["Period"] == 60 and kw["EvaluationPeriods"] == 1
        assert kw["Dimensions"] == [{"Name": "InstanceId", "Value": "i-001"}]
        sev = next(c.kwargs for c in cw.tag_resource.call_args_list
                   if APP_STATUS_METRIC_KEY in c.kwargs["ResourceARN"])
        assert {"Key": "Severity", "Value": "SEV-1"} in sev["Tags"]

    def test_instance_without_the_tag_gets_no_such_alarm(self):
        puts, _ = self._create(BASE_TAGS)
        assert not [n for n in puts if APP_STATUS_METRIC_KEY in n]
        assert puts, "다른 EC2 알람은 정상적으로 만들어져야 한다"


class TestPipelineIntegration:
    """알람이 울리면 파이프라인이 SEV-1로 읽고 억제하지 않는다."""

    def test_description_carries_sev1_and_survives_the_ingestor(self):
        from common.alarm_identity import identify_alarm
        from common.alarm_naming import _build_alarm_description
        desc = _build_alarm_description("EC2", "i-001", APP_STATUS_METRIC_KEY, "auto")
        identity = identify_alarm({
            "AlarmName": f"[EC2] srv {APP_STATUS_METRIC_KEY} > 0 (TagName: i-001)",
            "AlarmDescription": desc})
        assert identity.severity == "SEV-1"

    def test_sev1_app_failure_is_never_suppressed(self):
        from common.alert_event import from_eventbridge
        from common.alert_suppression import NOTIFY, SuppressionPolicy, decide
        from common.alarm_naming import _build_alarm_description
        from datetime import datetime, timedelta, timezone
        from tests.test_alert_event import state_change_event

        ev = state_change_event()
        ev["detail"]["alarmName"] = f"[EC2] srv {APP_STATUS_METRIC_KEY} > 0 (TagName: i-001)"
        ev["detail"]["configuration"]["description"] = _build_alarm_description(
            "EC2", "i-001", APP_STATUS_METRIC_KEY, "auto")
        alert = from_eventbridge(ev, customer_id="cust-1")
        assert alert.severity == "SEV-1"

        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        policy = SuppressionPolicy()
        # 방금 알렸고 진동 중이어도 SEV-1은 나간다
        decision = decide(alert, policy=policy, now=now,
                          last_notified_at=now - timedelta(seconds=5), is_flapping=True)
        assert decision.action == NOTIFY
