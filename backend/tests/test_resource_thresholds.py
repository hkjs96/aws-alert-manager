"""리소스별 임계치·판단 방식(M/N) 태그 — 엔진 해석과 편집 API (docs/specs/bulk-alarm-config)."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from api_handler.routes import resource_thresholds as rt
from common.alarm_manager import _parse_threshold_tags
from common.alarm_registry import _get_alarm_defs
from common.tag_resolver import get_eval_override, parse_eval


def _def(defs, metric):
    return next(d for d in defs if d["metric"] == metric)


class TestEvalTag:
    def test_parse(self):
        assert parse_eval("3/5") == (5, 3)
        assert parse_eval(" 1/1 ") == (1, 1)
        for bad in ("5/3", "0/1", "3", "a/b", "1/11", "", None):
            assert parse_eval(bad) is None

    def test_override_reads_legacy_name(self):
        assert get_eval_override({"Threshold_CPU_Eval": "3/5"}, "CPUUtilization") == (5, 3)
        assert get_eval_override({}, "CPUUtilization") is None

    def test_engine_applies_it(self):
        d = _def(_get_alarm_defs("EC2", {"Threshold_CPUUtilization_Eval": "4/6"}), "CPUUtilization")
        assert (d["evaluation_periods"], d["datapoints_to_alarm"]) == (6, 4)

    def test_invalid_tag_keeps_policy(self):
        policy = _def(_get_alarm_defs("EC2", {}), "CPUUtilization")
        d = _def(_get_alarm_defs("EC2", {"Threshold_CPUUtilization_Eval": "9/3"}), "CPUUtilization")
        assert d["evaluation_periods"] == policy["evaluation_periods"]

    def test_locked_definition_ignores_it(self):
        locked = next(d for d in _get_alarm_defs("EC2", {}) if rt.eval_locked(d))
        key = f"Threshold_{locked['metric']}_Eval"
        d = _def(_get_alarm_defs("EC2", {key: "3/5"}), locked["metric"])
        assert d["evaluation_periods"] == locked["evaluation_periods"]

    def test_eval_tag_is_not_a_dynamic_metric(self):
        tags = {"Threshold_CPUUtilization_Eval": "3/5", "Threshold_Foo_Eval": "2/3"}
        assert _parse_threshold_tags(tags, "EC2") == {}


class TestPlanTags:
    def test_set_and_eval(self):
        to_set, to_remove = rt.plan_tags("EC2", {"set": {"CPUUtilization": 90}, "eval": {"CPUUtilization": "3/5"}})
        assert to_set == {"Threshold_CPUUtilization": "90", "Threshold_CPUUtilization_Eval": "3/5"}
        # 레거시 이름 태그가 남아 있으면 그게 이긴다 — 함께 지운다
        assert to_remove == {"Threshold_CPU", "Threshold_CPU_Eval"}

    def test_clear_and_eval_reset(self):
        _, to_remove = rt.plan_tags("EC2", {"clear": ["CPUUtilization"], "eval": {"CPUUtilization": None}})
        assert {"Threshold_CPUUtilization", "Threshold_CPU", "Threshold_CPUUtilization_Eval"} <= to_remove

    def test_off(self):
        to_set, _ = rt.plan_tags("EC2", {"set": {"CPUUtilization": "off"}})
        assert to_set["Threshold_CPUUtilization"] == "off"

    @pytest.mark.parametrize("body", [
        {"set": {"CPUUtilization": -1}},
        {"set": {"CPUUtilization": "abc"}},
        {"set": {"NoSuchMetric": 1}},
        {"eval": {"CPUUtilization": "6/5"}},
        {"set": {"CPUUtilization": 1}, "clear": ["CPUUtilization"]},
        {"set": {"disk_used_percent": 80}},
    ])
    def test_rejects(self, body):
        with pytest.raises(ValueError):
            rt.plan_tags("EC2", body)

    def test_locked_eval_rejected(self):
        locked = next(d for d in rt.editable_defs("EC2", {}) if rt.eval_locked(d))
        with pytest.raises(ValueError):
            rt.plan_tags("EC2", {"eval": {locked["metric"]: "3/5"}})


class TestDescribe:
    def test_sources(self):
        rows = {r["metric"]: r for r in rt.describe(
            "EC2", {"Threshold_CPUUtilization": "90", "Threshold_CPUUtilization_Eval": "3/5"},
            {"mem_used_percent": 70.0})}
        cpu, mem = rows["CPUUtilization"], rows["mem_used_percent"]
        assert (cpu["value"], cpu["source"], cpu["eval"], cpu["eval_source"]) == (90.0, "resource", "3/5", "resource")
        assert (mem["value"], mem["source"], mem["customer_default"]) == (70.0, "customer", 70.0)
        assert cpu["eval_default"] != "3/5" or cpu["eval_source"] == "resource"
        assert "disk_used_percent" not in rows

    def test_off(self):
        row = next(r for r in rt.describe("EC2", {"Threshold_CPUUtilization": "off"}, {})
                   if r["metric"] == "CPUUtilization")
        assert row["off"] and row["value"] is None


class TestWrite:
    RES = {"resource_id": "i-1", "type": "EC2", "account_id": "771283576189", "region": "ap-northeast-2",
           "arn": "arn:aws:ec2:ap-northeast-2:771283576189:instance/i-1", "monitoring": True}

    def _put(self, body, client):
        event = {"pathParameters": {"id": "i-1"}, "body": __import__("json").dumps(body)}
        with patch.object(rt, "_load", return_value=(dict(self.RES), None)), \
             patch.object(rt.res, "_live_resource_tags", return_value={"Name": "web", "Threshold_CPU": "70"}), \
             patch.object(rt, "_tagging_client", return_value=client), \
             patch.object(rt.res, "_customer_defaults_for", return_value={}), \
             patch.object(rt, "_sync_alarms", return_value=True) as sync:
            return rt.update_resource_thresholds(event), sync

    def test_writes_then_syncs_with_after_tags(self):
        client = MagicMock()
        client.tag_resources.return_value = {}
        client.untag_resources.return_value = {}
        out, sync = self._put({"set": {"CPUUtilization": 90}}, client)
        assert out["statusCode"] == 200
        client.tag_resources.assert_called_once()
        assert client.untag_resources.call_args.kwargs["TagKeys"] == ["Threshold_CPU"]
        after = sync.call_args.args[1]
        assert after["Threshold_CPUUtilization"] == "90" and "Threshold_CPU" not in after

    def test_denied_by_rgt_map_is_role_update_required(self):
        client = MagicMock()
        client.tag_resources.return_value = {"FailedResourcesMap": {self.RES["arn"]: {
            "ErrorCode": "InvalidParameterException",
            "ErrorMessage": "User is not authorized to perform: ec2:CreateTags"}}}
        out, sync = self._put({"set": {"CPUUtilization": 90}}, client)
        assert out["statusCode"] == 403 and "ROLE_UPDATE_REQUIRED" in out["body"]
        sync.assert_not_called()

    def test_denied_exception(self):
        client = MagicMock()
        client.tag_resources.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "TagResources")
        out, _ = self._put({"set": {"CPUUtilization": 90}}, client)
        assert out["statusCode"] == 403

    def test_empty_change_rejected(self):
        out, _ = self._put({}, MagicMock())
        assert out["statusCode"] == 400
