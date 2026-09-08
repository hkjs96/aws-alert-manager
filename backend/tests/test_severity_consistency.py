"""
Severity는 태그와 설명 메타데이터 두 곳에 있고, 알림 파이프라인은 설명을 읽는다.

둘이 갈라지면 SEV-1 면제가 엉뚱한 등급에 걸린다. 여기서 고정하는 것:
- 태그를 쓰는 모든 경로가 같은 값을 설명에도 쓴다 (F1, 정적 검사 + 라우트 검사)
- 설명의 값은 SEV-1~5 밖이면 버린다 (F2)
- 옛 알람은 동기화가 재생성 없이 제자리에서 설명을 채운다 (F3)
(docs/specs/alert-pipeline/review-personas-2026-09-08.md)
"""

import ast
import inspect
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from patch_helpers import alarm_config_fields
from test_api_routes import _alarm, _event

from common.alarm_identity import identify_alarm
from common.alarm_naming import (
    _build_alarm_description,
    _parse_alarm_metadata,
    set_description_severity,
)
from common.alarm_registry import SEVERITIES, get_severity, is_valid_severity


def _sev(desc: str) -> str:
    return _parse_alarm_metadata(desc)["severity"]


def _legacy_desc(prefix="Auto-created", rid="i-001", mk="CPUUtilization") -> str:
    """severity가 없던 시절의 설명."""
    meta = json.dumps({"metric_key": mk, "resource_id": rid, "resource_type": "EC2"},
                      separators=(",", ":"))
    return f"{prefix} | {meta}"


class TestSeveritySet:
    @pytest.mark.parametrize("value", SEVERITIES)
    def test_accepts_canonical(self, value):
        assert is_valid_severity(value)

    @pytest.mark.parametrize("value", ["", "sev-1", "SEV-0", "SEV-6", "urgent", None, 1])
    def test_rejects_everything_else(self, value):
        assert not is_valid_severity(value)


class TestSetDescriptionSeverity:
    def test_replaces_existing_severity_and_keeps_prefix(self):
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto-created", severity="SEV-3")
        out = set_description_severity(desc, "SEV-1")
        assert _sev(out) == "SEV-1"
        assert out.startswith("Auto-created | ")
        meta = _parse_alarm_metadata(out)
        assert (meta["resource_type"], meta["resource_id"], meta["metric_key"]) == ("EC2", "i-001", "CPUUtilization")

    def test_adds_severity_to_old_metadata(self):
        out = set_description_severity(_legacy_desc(), "SEV-2")
        assert _sev(out) == "SEV-2"
        assert out.startswith("Auto-created | ")

    def test_metadata_without_prefix(self):
        out = set_description_severity(_build_alarm_description("EC2", "i-001", "CPUUtilization"), "SEV-4")
        assert out.startswith("{")
        assert _sev(out) == "SEV-4"

    def test_free_text_gets_metadata_when_identity_known(self):
        out = set_description_severity("CPU high on web-1", "SEV-2",
                                       resource_type="EC2", resource_id="i-001", metric_key="CPUUtilization")
        assert out.startswith("CPU high on web-1 | ")
        meta = _parse_alarm_metadata(out)
        assert meta["resource_id"] == "i-001"
        assert meta["severity"] == "SEV-2"

    def test_free_text_untouched_without_identity(self):
        assert set_description_severity("CPU high on web-1", "SEV-2") == "CPU high on web-1"
        assert set_description_severity("", "SEV-2") == ""

    def test_long_prefix_never_cuts_the_json(self):
        out = set_description_severity("x" * 2000, "SEV-2",
                                       resource_type="EC2", resource_id="i-001", metric_key="CPUUtilization")
        assert len(out) <= 1024
        assert _sev(out) == "SEV-2"

    def test_identity_drops_invalid_severity(self):
        default = get_severity("CPUUtilization")
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization").replace(
            f'"severity":"{default}"', '"severity":"urgent"')
        assert '"urgent"' in desc
        identity = identify_alarm({"AlarmName": "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
                                   "AlarmDescription": desc})
        assert identity.resource_id == "i-001"
        assert identity.severity == ""


class TestEveryTagWriterWritesDescription:
    """Severity 태그를 쓰는 함수는 같은 함수 안에서 설명도 만든다 — 정적 검사.

    F1은 경로별 테스트가 라우트 두 개를 안 봐서 새어 나갔다. 새 경로가 생겨도 잡히도록
    소스를 훑는다.
    """

    @staticmethod
    def _functions(module):
        src = inspect.getsource(module)
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef):
                yield node.name, ast.get_source_segment(src, node)

    def test_resources_routes(self):
        from api_handler.routes import resources
        helpers = ("_build_alarm_description(", "set_description_severity(", "_metric_alarm_update_kwargs(")
        functions = dict(self._functions(resources))
        offenders = [
            name for name, body in functions.items()
            if '"Severity"' in body and ("tag_resource(" in body or "put_metric_alarm(" in body)
            and not any(h in body for h in helpers)
        ]
        assert offenders == []
        assert "set_description_severity(" in functions["_metric_alarm_update_kwargs"]

    def test_alarm_builder(self):
        from common import alarm_builder
        offenders = [
            name for name, body in self._functions(alarm_builder)
            if name != "_tag_alarm_with_severity" and "_tag_alarm_with_severity(" in body
            and "_build_alarm_description(" not in body
        ]
        assert offenders == []


class TestRoutesKeepTagAndDescriptionTogether:
    @staticmethod
    def _existing(desc: str) -> dict:
        return {
            **_alarm("[EC2] server CPU >80% (TagName: i-001)", metric="CPUUtilization"),
            "AlarmArn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:test",
            "AlarmDescription": desc,
            "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}],
            "Period": 300,
            "EvaluationPeriods": 1,
            "ActionsEnabled": True,
            "AlarmActions": [],
            "OKActions": [],
            "InsufficientDataActions": [],
            "TreatMissingData": "notBreaching",
            "Statistic": "Average",
        }

    @staticmethod
    def _put(alarms, config):
        mock_cw, mock_ec2 = MagicMock(), MagicMock()
        with patch("api_handler.routes.resources.list_alarms", return_value=alarms), \
             patch("api_handler.routes.resources._get_cw_client_for_region", return_value=mock_cw), \
             patch("api_handler.routes.resources._get_ec2_client_for_region", return_value=mock_ec2):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("PUT", "/resources/i-001/alarms",
                       body={"configs": [{"metric_key": "CPUUtilization", "threshold": 70,
                                          "monitoring": True, "unit": "Percent", "direction": ">",
                                          **config}]},
                       path_params={"id": "i-001"}),
                None,
            )
        return resp, mock_cw

    def test_update_rewrites_description_severity_with_the_tag(self):
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto-created", severity="SEV-3")
        resp, cw = self._put([self._existing(desc)], {"severity": "SEV-1"})
        assert resp["statusCode"] == 200, resp["body"]
        kwargs = cw.put_metric_alarm.call_args.kwargs
        assert _sev(kwargs["AlarmDescription"]) == "SEV-1"
        assert kwargs["AlarmDescription"].startswith("Auto-created | ")
        cw.tag_resource.assert_called_once()
        assert {"Key": "Severity", "Value": "SEV-1"} in cw.tag_resource.call_args.kwargs["Tags"]
        # 관리 알람 이름은 "(TagName: ...)"로 콜론을 품는다 — 마지막 콜론으로 자르면 ARN이 깨져
        # TagResource가 ResourceNotFound로 조용히 실패한다(라이브 검증에서 발견, F9).
        assert cw.tag_resource.call_args.kwargs["ResourceARN"] == (
            "arn:aws:cloudwatch:us-east-1:123456789012:alarm:"
            "[EC2] server CPUUtilization > 70% (TagName: i-001)")

    @pytest.mark.parametrize("arn, name, expected", [
        ("arn:aws:cloudwatch:us-east-1:1:alarm:[EC2] a CPU > 80% (TagName: i-1)",
         "[EC2] a CPU > 70% (TagName: i-1)",
         "arn:aws:cloudwatch:us-east-1:1:alarm:[EC2] a CPU > 70% (TagName: i-1)"),
        ("arn:aws:cloudwatch:us-east-1:1:alarm:plain", "other", "arn:aws:cloudwatch:us-east-1:1:alarm:other"),
        ("not-an-alarm-arn", "x", None),
        ("", "x", None),
    ])
    def test_alarm_arn_for_name_survives_colons_in_names(self, arn, name, expected):
        from api_handler.routes.resources import _alarm_arn_for_name
        assert _alarm_arn_for_name({"AlarmArn": arn}, name) == expected

    def test_update_fills_severity_into_old_description(self):
        resp, cw = self._put([self._existing(_legacy_desc())], {"severity": "SEV-2"})
        assert resp["statusCode"] == 200, resp["body"]
        assert _sev(cw.put_metric_alarm.call_args.kwargs["AlarmDescription"]) == "SEV-2"

    def test_update_without_severity_keeps_description(self):
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto-created", severity="SEV-3")
        resp, cw = self._put([self._existing(desc)], {})
        assert resp["statusCode"] == 200, resp["body"]
        assert cw.put_metric_alarm.call_args.kwargs["AlarmDescription"] == desc
        cw.tag_resource.assert_not_called()

    def test_update_rejects_unknown_severity(self):
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto-created", severity="SEV-3")
        resp, cw = self._put([self._existing(desc)], {"severity": "urgent"})
        assert resp["statusCode"] == 400, resp["body"]
        cw.put_metric_alarm.assert_not_called()
        cw.tag_resource.assert_not_called()

    @staticmethod
    def _post_custom(body):
        mock_cw = MagicMock()
        existing = [_alarm("[EC2] server CPUUtilization > 80% (TagName: i-001)")]
        with patch("api_handler.routes.resources.list_alarms", return_value=existing), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw), \
             patch("api_handler.routes.resources._get_instance_name", return_value="server"), \
             patch("api_handler.routes.resources._resource_dim_hints", return_value={}), \
             patch("common.dimension_builder._resolve_metric_dimensions",
                   return_value=("AWS/EC2", [{"Name": "InstanceId", "Value": "i-001"}])):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("POST", "/resources/i-001/alarms", body=body, path_params={"id": "i-001"}),
                None,
            )
        return resp, mock_cw

    def test_custom_alarm_stamps_chosen_severity_in_both(self):
        resp, cw = self._post_custom({"metric_name": "NetworkIn", "threshold": 1000, "severity": "SEV-1"})
        assert resp["statusCode"] == 201, resp["body"]
        kwargs = cw.put_metric_alarm.call_args.kwargs
        assert _sev(kwargs["AlarmDescription"]) == "SEV-1"
        assert kwargs["Tags"] == [{"Key": "Severity", "Value": "SEV-1"}]

    def test_custom_alarm_rejects_unknown_severity(self):
        resp, cw = self._post_custom({"metric_name": "NetworkIn", "threshold": 1000, "severity": "P1"})
        assert resp["statusCode"] == 400, resp["body"]
        cw.put_metric_alarm.assert_not_called()


class TestSyncRefreshesLegacyDescriptions:
    """옛 알람의 설명은 재생성이 아니라 제자리 갱신으로 채운다 — 상태·이력·태그를 지키기 위해."""

    NAME = "[EC2] srv CPUUtilization > 80% (TagName: i-001)"
    DEF = {"metric": "CPUUtilization", "metric_name": "CPUUtilization", "stat": "Average",
           "period": 300, "evaluation_periods": 1, "comparison": "GreaterThanThreshold",
           "treat_missing_data": "breaching"}

    @classmethod
    def _std_alarm(cls, desc: str) -> dict:
        return {
            "AlarmName": cls.NAME,
            "AlarmArn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:x",
            "AlarmDescription": desc,
            "Threshold": 80.0, "MetricName": "CPUUtilization", "Namespace": "AWS/EC2",
            "Statistic": "Average", "Period": 300, "EvaluationPeriods": 1,
            "ComparisonOperator": "GreaterThanThreshold", "TreatMissingData": "breaching",
            "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}], "ActionsEnabled": True,
            "AlarmActions": ["arn:aws:sns:us-east-1:123456789012:alert"],
            "OKActions": [], "InsufficientDataActions": [],
        }

    @staticmethod
    def _result():
        return {"created": [], "updated": [], "ok": [], "deleted": []}

    def test_missing_severity_is_noted_not_recreated(self):
        from common.alarm_sync import _sync_standard_alarms
        alarm = self._std_alarm(_legacy_desc())
        result = self._result()
        changed = _sync_standard_alarms(self.DEF, {"CPUUtilization": alarm}, {}, result)
        assert changed is False
        assert result["updated"] == []
        assert result["ok"] == [self.NAME]
        assert result["refreshed"] == [self.NAME]

    def test_present_severity_needs_nothing(self):
        from common.alarm_sync import _sync_standard_alarms
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto", severity="SEV-3")
        result = self._result()
        _sync_standard_alarms(self.DEF, {"CPUUtilization": self._std_alarm(desc)}, {}, result)
        assert "refreshed" not in result
        assert result["ok"] == [self.NAME]

    def test_garbage_severity_counts_as_missing(self):
        from common.alarm_sync import _sync_standard_alarms
        desc = _legacy_desc().replace('"resource_type":"EC2"', '"resource_type":"EC2","severity":"urgent"')
        result = self._result()
        _sync_standard_alarms(self.DEF, {"CPUUtilization": self._std_alarm(desc)}, {}, result)
        assert result["refreshed"] == [self.NAME]

    def _cw(self, alarm: dict, tags=None) -> MagicMock:
        cw = MagicMock()
        cw.describe_alarms.return_value = {"MetricAlarms": [alarm]}
        cw.list_tags_for_resource.return_value = {"Tags": tags or []}
        return cw

    def test_refresh_prefers_the_tag_and_keeps_everything_else(self):
        from common.alarm_sync import _refresh_alarm_description
        alarm = self._std_alarm(_legacy_desc())
        cw = self._cw(alarm, [{"Key": "Severity", "Value": "SEV-2"}, {"Key": "ManagedBy", "Value": "AlarmManager"}])
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is True
        kwargs = cw.put_metric_alarm.call_args.kwargs
        assert _sev(kwargs["AlarmDescription"]) == "SEV-2"
        assert kwargs["AlarmDescription"].startswith("Auto-created | ")
        for field in ("AlarmName", "Threshold", "Dimensions", "AlarmActions", "Period",
                      "EvaluationPeriods", "Statistic", "TreatMissingData", "ComparisonOperator"):
            assert kwargs[field] == alarm[field]
        assert "Tags" not in kwargs
        assert "AlarmArn" not in kwargs
        cw.delete_alarms.assert_not_called()
        cw.tag_resource.assert_not_called()

    def test_refresh_falls_back_to_registry_without_tag(self):
        from common.alarm_sync import _refresh_alarm_description
        cw = self._cw(self._std_alarm(_legacy_desc()))
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is True
        assert _sev(cw.put_metric_alarm.call_args.kwargs["AlarmDescription"]) == get_severity("CPUUtilization")

    def test_refresh_survives_tag_read_failure(self):
        from common.alarm_sync import _refresh_alarm_description
        cw = self._cw(self._std_alarm(_legacy_desc()))
        cw.list_tags_for_resource.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "ListTagsForResource")
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is True
        assert _sev(cw.put_metric_alarm.call_args.kwargs["AlarmDescription"]) == get_severity("CPUUtilization")

    def test_refresh_is_a_no_op_when_current(self):
        from common.alarm_sync import _refresh_alarm_description
        desc = _build_alarm_description("EC2", "i-001", "CPUUtilization", "Auto", severity="SEV-3")
        cw = self._cw(self._std_alarm(desc), [{"Key": "Severity", "Value": "SEV-3"}])
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is False
        cw.put_metric_alarm.assert_not_called()

    def test_refresh_handles_name_only_legacy(self):
        from common.alarm_sync import _refresh_alarm_description
        alarm = self._std_alarm("Auto-created by AWS Monitoring Engine")
        cw = self._cw(alarm, [{"Key": "Severity", "Value": "SEV-1"}])
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is True
        desc = cw.put_metric_alarm.call_args.kwargs["AlarmDescription"]
        meta = _parse_alarm_metadata(desc)
        assert desc.startswith("Auto-created by AWS Monitoring Engine | ")
        assert (meta["resource_type"], meta["resource_id"], meta["metric_key"]) == ("EC2", "i-001", "CPUUtilization")
        assert meta["severity"] == "SEV-1"

    def test_refresh_put_failure_is_logged_not_raised(self):
        from common.alarm_sync import _refresh_alarm_description
        cw = self._cw(self._std_alarm(_legacy_desc()))
        cw.put_metric_alarm.side_effect = ClientError(
            {"Error": {"Code": "Throttling", "Message": "x"}}, "PutMetricAlarm")
        assert _refresh_alarm_description(self.NAME, "i-001", "EC2", cw=cw) is False

    def test_sync_refreshes_ok_alarms_in_place(self, monkeypatch):
        """sync_alarms_for_resource 끝에서 설정이 맞는 옛 알람만 설명을 채운다 — 삭제 없음."""
        from common._clients import _get_cw_client
        from common.alarm_manager import sync_alarms_for_resource
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")
        _get_cw_client.cache_clear()

        existing = [
            "[EC2] srv CPUUtilization > 80% (TagName: i-001)",
            "[EC2] srv mem_used_percent > 80% (TagName: i-001)",
            "[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)",
            "[EC2] srv StatusCheckFailed > 0 (TagName: i-001)",
        ]

        def describe(**kwargs):
            alarms = []
            for n in kwargs.get("AlarmNames", []):
                if "CPUUtilization" in n:
                    mk, thr, cw_metric = "CPU", 80.0, "CPUUtilization"
                elif "mem_used_percent" in n:
                    mk, thr, cw_metric = "Memory", 80.0, "mem_used_percent"
                elif "StatusCheckFailed" in n:
                    mk, thr, cw_metric = "StatusCheckFailed", 0.0, "StatusCheckFailed"
                else:
                    mk, thr, cw_metric = "Disk_root", 80.0, "disk_used_percent"
                alarms.append({
                    "AlarmName": n,
                    "AlarmArn": f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{n}",
                    "Threshold": thr,
                    "MetricName": cw_metric,
                    "AlarmDescription": _legacy_desc(mk=mk),
                    "Dimensions": [{"Name": "path", "Value": "/"}] if "disk" in n else [],
                    **alarm_config_fields("EC2", cw_metric),
                })
            return {"MetricAlarms": alarms}

        mock_cw = MagicMock()
        mock_cw.describe_alarms.side_effect = describe
        mock_cw.list_tags_for_resource.return_value = {"Tags": [{"Key": "Severity", "Value": "SEV-2"}]}
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager._find_alarms_for_resource", return_value=existing):
            result = sync_alarms_for_resource("i-001", "EC2", {})

        assert len(result["ok"]) == 4
        assert result["updated"] == [] and result["created"] == []
        assert sorted(result["refreshed"]) == sorted(existing)
        assert mock_cw.put_metric_alarm.call_count == 4
        for call in mock_cw.put_metric_alarm.call_args_list:
            assert _sev(call.kwargs["AlarmDescription"]) == "SEV-2"
        mock_cw.delete_alarms.assert_not_called()
