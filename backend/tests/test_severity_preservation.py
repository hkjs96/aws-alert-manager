"""
재생성 시 수동 등급 보존 — 사용자 결정(2026-09-08, review-personas F8): **수동 등급이 레지스트리 기본값을 이긴다.**

재생성 경로 셋(이름별 재생성, 전체 재생성, 동적 알람 드리프트) 모두 지우기 전에 Severity 태그를 읽어
새 알람의 태그와 설명에 그대로 쓴다. 태그가 기본값과 같거나 없으면 기본값(기존 동작).
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from common.alarm_builder import _severity_overrides, _tagged_severity
from common.alarm_naming import _build_alarm_description, _parse_alarm_metadata
from common.alarm_registry import get_severity

ARN = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:"
NAME = "[EC2] srv CPUUtilization > 80% (TagName: i-001)"
TAGS = {"Monitoring": "on", "Name": "srv"}


def _info(name: str, metric_key: str, *, arn: bool = True, **extra) -> dict:
    d = {
        "AlarmName": name,
        "AlarmDescription": _build_alarm_description("EC2", "i-001", metric_key, "Auto"),
        "MetricName": metric_key, "Namespace": "AWS/EC2", "Threshold": 80.0,
        "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}], "Statistic": "Average",
        "Period": 300, "EvaluationPeriods": 1, "ComparisonOperator": "GreaterThanThreshold",
        "TreatMissingData": "notBreaching",
    }
    if arn:
        d["AlarmArn"] = ARN + name
    d.update(extra)
    return d


def _cw(tags_by_arn: dict[str, str]) -> MagicMock:
    cw = MagicMock()
    cw.meta.region_name = "us-east-1"

    def _tags(ResourceARN):
        sev = tags_by_arn.get(ResourceARN)
        return {"Tags": [{"Key": "Severity", "Value": sev}] if sev else []}
    cw.list_tags_for_resource.side_effect = _tags
    return cw


def _sev(desc: str) -> str:
    return _parse_alarm_metadata(desc)["severity"]


class TestSeverityOverrides:
    def test_manual_grade_is_kept_default_is_not(self):
        cpu, mem = _info(NAME, "CPUUtilization"), _info("[EC2] srv mem (TagName: i-001)", "mem_used_percent")
        cw = _cw({cpu["AlarmArn"]: "SEV-1", mem["AlarmArn"]: get_severity("mem_used_percent")})
        assert _severity_overrides(cw, [cpu, mem]) == {"CPUUtilization": "SEV-1"}

    def test_missing_arn_is_built_from_name(self):
        info = _info(NAME, "CPUUtilization", arn=False)
        cw = _cw({ARN + NAME: "SEV-2"})
        with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"):
            assert _severity_overrides(cw, [info]) == {"CPUUtilization": "SEV-2"}

    def test_tag_read_failure_means_no_override(self):
        cw = _cw({})
        cw.list_tags_for_resource.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "ListTagsForResource")
        assert _severity_overrides(cw, [_info(NAME, "CPUUtilization")]) == {}
        assert _tagged_severity(cw, ARN + NAME) == ""

    def test_garbage_tag_is_ignored(self):
        cw = _cw({ARN + NAME: "urgent"})
        assert _severity_overrides(cw, [_info(NAME, "CPUUtilization")]) == {}


class TestRecreateByNameKeepsManualSeverity:
    def _recreate(self, tag: str | None) -> MagicMock:
        from common.alarm_builder import _recreate_alarm_by_name
        cw = _cw({ARN + NAME: tag} if tag else {})
        cw.describe_alarms.return_value = {"MetricAlarms": [_info(NAME, "CPUUtilization")]}
        with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"), \
             patch("common.alarm_builder._get_sns_alert_arn", return_value=""):
            _recreate_alarm_by_name(NAME, "i-001", "EC2", TAGS, cw=cw)
        return cw

    def test_manual_grade_lands_in_tag_and_description(self):
        cw = self._recreate("SEV-1")
        cw.delete_alarms.assert_called_once_with(AlarmNames=[NAME])
        put = cw.put_metric_alarm.call_args.kwargs
        assert "CPUUtilization" in put["AlarmName"]
        assert _sev(put["AlarmDescription"]) == "SEV-1"
        tags = cw.tag_resource.call_args.kwargs["Tags"]
        assert {"Key": "Severity", "Value": "SEV-1"} in tags
        assert {"Key": "ManagedBy", "Value": "AlarmManager"} in tags

    def test_default_grade_stays_default(self):
        cw = self._recreate(None)
        put = cw.put_metric_alarm.call_args.kwargs
        assert _sev(put["AlarmDescription"]) == get_severity("CPUUtilization")
        assert {"Key": "Severity", "Value": get_severity("CPUUtilization")} in cw.tag_resource.call_args.kwargs["Tags"]

    def test_explicit_overrides_skip_the_tag_read(self):
        from common.alarm_builder import _recreate_alarm_by_name
        cw = _cw({ARN + NAME: "SEV-2"})
        cw.describe_alarms.return_value = {"MetricAlarms": [_info(NAME, "CPUUtilization")]}
        with patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"), \
             patch("common.alarm_builder._get_sns_alert_arn", return_value=""):
            _recreate_alarm_by_name(NAME, "i-001", "EC2", TAGS, cw=cw,
                                    severity_overrides={"CPUUtilization": "SEV-1"})
        cw.list_tags_for_resource.assert_not_called()
        assert _sev(cw.put_metric_alarm.call_args.kwargs["AlarmDescription"]) == "SEV-1"


class TestFullRecreateKeepsManualSeverity:
    def test_existing_manual_grade_survives_delete_and_create(self):
        from common.alarm_manager import create_alarms_for_resource
        cw = _cw({ARN + NAME: "SEV-1"})
        cw.describe_alarms.return_value = {"MetricAlarms": [_info(NAME, "CPUUtilization")]}
        with patch("common.alarm_manager._find_alarms_for_resource", return_value=[NAME]), \
             patch("common.alarm_manager._delete_all_alarms_for_resource", return_value=[NAME]) as delete, \
             patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"), \
             patch("common._clients._get_cw_client", return_value=cw):
            created = create_alarms_for_resource("i-001", "EC2", TAGS, cw=cw)
        delete.assert_called_once()
        assert created
        puts = {c.kwargs["AlarmName"]: c.kwargs for c in cw.put_metric_alarm.call_args_list}
        cpu = next(k for n, k in puts.items() if "CPUUtilization" in n)
        assert _sev(cpu["AlarmDescription"]) == "SEV-1"
        others = [k for n, k in puts.items() if "CPUUtilization" not in n]
        assert others, "다른 표준 알람도 만들어져야 한다"
        for k in others:
            meta = _parse_alarm_metadata(k["AlarmDescription"])
            assert meta["severity"] == get_severity(meta["metric_key"])
        cpu_tag = next(c.kwargs for c in cw.tag_resource.call_args_list if "CPUUtilization" in c.kwargs["ResourceARN"])
        assert {"Key": "Severity", "Value": "SEV-1"} in cpu_tag["Tags"]

    def test_new_resource_reads_no_tags(self):
        from common.alarm_manager import create_alarms_for_resource
        cw = _cw({})
        with patch("common.alarm_manager._find_alarms_for_resource", return_value=[]), \
             patch("common.alarm_manager._delete_all_alarms_for_resource", return_value=[]), \
             patch("common.alarm_builder._get_aws_account_id", return_value="123456789012"), \
             patch("common._clients._get_cw_client", return_value=cw):
            create_alarms_for_resource("i-001", "EC2", TAGS, cw=cw)
        cw.list_tags_for_resource.assert_not_called()
        cw.describe_alarms.assert_not_called()


class TestDynamicDriftKeepsManualSeverity:
    def test_recreated_dynamic_alarm_gets_the_override(self):
        from common.alarm_sync import _sync_dynamic_alarms
        name = "[EC2] srv NetworkIn > 100 (TagName: i-001)"
        info = _info(name, "NetworkIn", Threshold=100.0, EvaluationPeriods=1, DatapointsToAlarm=1)
        cw = _cw({ARN + name: "SEV-1"})
        result = {"created": [], "updated": [], "ok": [], "deleted": []}
        with patch("common.alarm_sync._create_dynamic_alarm") as create, \
             patch("common.alarm_sync._delete_alarm_names") as delete, \
             patch("common.alarm_manager._get_sns_alert_arn", return_value=""), \
             patch("common.alarm_manager._parse_threshold_tags",
                   return_value={"NetworkIn": (200.0, "GreaterThanThreshold")}):
            _sync_dynamic_alarms({"NetworkIn": info}, "i-001", "EC2",
                                 {**TAGS, "Threshold_NetworkIn": "200"}, result, cw=cw)
        delete.assert_called_once_with(cw, [name])
        assert create.call_args.kwargs["severity_overrides"] == {"NetworkIn": "SEV-1"}
        assert result["updated"] == [name]
