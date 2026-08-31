"""
알람 정체성 해석 (common/alarm_identity.py) 테스트

- 메타데이터 우선 / 이름 폴백 / 레거시 EC2 폴백
- ALB 계열: Full ARN이 정본, short ID는 tag_name — 양쪽 키로 매칭
- 호출부(daily_monitor 인벤토리·orphan 분류, resources 라우트, AlarmIndex)의 듀얼 리드
- 가드: 이름 파싱 정규식이 alarm_identity/alarm_naming/alarm_search 밖에 재유입되면 실패
"""

import pathlib
import re

import pytest

from common.alarm_identity import (
    AlarmIdentity,
    group_alarms_by_resource,
    identify_alarm,
    identify_alarm_name,
    parse_alarm_name,
)
from common.alarm_naming import _build_alarm_description

ALB_ARN = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/web/50dc6c495c0c9188"
ALB_SHORT = "web/50dc6c495c0c9188"


def _alarm(name, *, rtype=None, rid=None, metric_key="CPUUtilization", desc=None):
    alarm = {"AlarmName": name, "AlarmArn": f"arn:aws:cloudwatch:ap-northeast-2:123456789012:alarm:{name}"}
    if desc is not None:
        alarm["AlarmDescription"] = desc
    elif rtype and rid:
        alarm["AlarmDescription"] = _build_alarm_description(rtype, rid, metric_key, "human")
    return alarm


class TestParseName:
    def test_mark_format(self):
        assert parse_alarm_name("[EC2] srv CPUUtilization > 80% (TagName: i-001)") == ("EC2", "i-001")

    def test_non_managed(self):
        assert parse_alarm_name("[RemediationDLQ] messages > 0") is None
        assert parse_alarm_name("") is None

    def test_legacy_ec2_only_via_identify(self):
        assert parse_alarm_name("i-0abc-CPU-prod") is None
        ident = identify_alarm_name("i-0abc-CPU-prod")
        assert ident == AlarmIdentity("EC2", "i-0abc", "i-0abc", None, "legacy")


class TestIdentifyAlarm:
    def test_metadata_wins_over_name(self):
        alarm = _alarm(f"[ALB] web HTTPCode_ELB_5XX_Count > 10 (TagName: {ALB_SHORT})",
                       rtype="ALB", rid=ALB_ARN, metric_key="HTTPCode_ELB_5XX_Count")
        ident = identify_alarm(alarm)
        assert ident.source == "metadata"
        assert ident.resource_id == ALB_ARN          # 정본 = Full ARN
        assert ident.tag_name == ALB_SHORT            # 이름의 short ID 보존
        assert ident.resource_type == "ALB"
        assert ident.metric_key == "HTTPCode_ELB_5XX_Count"
        assert ident.match_keys == {ALB_ARN, ALB_SHORT}
        assert ident.matches(ALB_ARN) and ident.matches(ALB_SHORT)
        assert not ident.matches("other")

    def test_name_fallback_without_metadata(self):
        ident = identify_alarm(_alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)"))
        assert ident.source == "name"
        assert ident.resource_id == "i-001" == ident.tag_name
        assert ident.metric_key is None

    def test_legacy_description_without_json_falls_back_to_name(self):
        ident = identify_alarm(_alarm("[RDS] db CPUUtilization > 80% (TagName: db-1)",
                                      desc="Legacy alarm without metadata"))
        assert ident.source == "name" and ident.resource_id == "db-1"

    def test_incomplete_metadata_keeps_name_identity_but_lifts_metric_key(self):
        ident = identify_alarm(_alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)",
                                      desc='{"metric_key":"CPUUtilization"}'))
        assert ident.source == "name"
        assert ident.resource_id == "i-001"
        assert ident.metric_key == "CPUUtilization"

    def test_unmanaged_alarm_is_none(self):
        assert identify_alarm({"AlarmName": "[RemediationDLQ] messages > 0"}) is None
        assert identify_alarm({"AlarmName": "", "AlarmDescription": ""}) is None

    def test_metadata_only_alarm_renamed_by_hand(self):
        # 이름이 바뀌어도 메타데이터가 있으면 정체성이 유지된다 (이름 = 표시)
        ident = identify_alarm(_alarm("my custom name", rtype="EC2", rid="i-001"))
        assert ident.source == "metadata"
        assert ident.resource_id == "i-001" and ident.tag_name == ""
        assert ident.match_keys == {"i-001"}


class TestGrouping:
    def test_groups_under_both_full_and_short_keys(self):
        alb = _alarm(f"[ALB] web x > 1 (TagName: {ALB_SHORT})", rtype="ALB", rid=ALB_ARN)
        ec2 = _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)")
        grouped = group_alarms_by_resource([alb, ec2, {"AlarmName": "[RemediationDLQ] x"}])
        assert grouped[ALB_ARN] == [alb]
        assert grouped[ALB_SHORT] == [alb]
        assert grouped["i-001"] == [ec2]
        assert len(grouped) == 3


class TestDailyMonitorCallers:
    def test_inventory_alarm_count_joins_alb_by_full_arn(self):
        from daily_monitor.lambda_handler import _build_resource_items

        alb = _alarm(f"[ALB] web x > 1 (TagName: {ALB_SHORT})", rtype="ALB", rid=ALB_ARN)
        alb["StateValue"] = "ALARM"
        alb["Tags"] = [{"Key": "Severity", "Value": "SEV-3"}]
        discovered = [{"resource_id": ALB_ARN, "account_id": "123456789012", "type": "ALB",
                       "region": "ap-northeast-2", "monitoring": True, "tags": {}}]
        items = _build_resource_items(discovered, group_alarms_by_resource([alb]))
        assert items[0]["alarm_count"] == 1
        assert items[0]["alarm_state"] == "ALARM"
        assert items[0]["alarm_names"] == [alb["AlarmName"]]

    def test_alarm_snapshot_uses_full_id_and_keeps_tag_name(self):
        from daily_monitor.lambda_handler import _build_alarm_item

        alb = _alarm(f"[ALB] web x > 1 (TagName: {ALB_SHORT})", rtype="ALB", rid=ALB_ARN)
        arn_parts = alb["AlarmArn"].split(":")
        item = _build_alarm_item(alb, f"alarm#{alb['AlarmArn']}", "123456789012", arn_parts)
        assert item["resource"] == ALB_ARN
        assert item["tag_name"] == ALB_SHORT
        assert item["type"] == "ALB"

    def test_orphan_classification_keys_by_short_id_for_collectors(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result: dict = {}
        _classify_alarm(_alarm(f"[ALB] web x > 1 (TagName: {ALB_SHORT})", rtype="ALB", rid=ALB_ARN), result)
        _classify_alarm(_alarm("i-0abc-CPU-prod"), result)
        _classify_alarm({"AlarmName": "[RemediationDLQ] x"}, result)
        assert result == {
            "ALB": {ALB_SHORT: [f"[ALB] web x > 1 (TagName: {ALB_SHORT})"]},
            "EC2": {"i-0abc": ["i-0abc-CPU-prod"]},
        }


class TestResourcesRouteCallers:
    def test_alarms_for_resource_matches_full_arn_and_short_id(self):
        from api_handler.routes.resources import _alarms_for_resource, _get_resource_type, _get_tag_name

        alb = _alarm(f"[ALB] web x > 1 (TagName: {ALB_SHORT})", rtype="ALB", rid=ALB_ARN)
        ec2 = _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)")
        assert _alarms_for_resource([alb, ec2], ALB_ARN) == [alb]
        assert _alarms_for_resource([alb, ec2], ALB_SHORT) == [alb]
        assert _alarms_for_resource([alb, ec2], "i-001") == [ec2]
        assert _get_resource_type(alb) == "ALB"
        # 이름 재생성 경로는 short ID를 유지해야 서픽스가 바뀌지 않는다
        assert _get_tag_name(alb) == ALB_SHORT


class TestAlarmIndexMetadataMatch:
    def test_index_matches_by_metadata_even_when_name_differs(self):
        from common.alarm_index import AlarmIndex

        renamed = _alarm("[EC2] renamed-by-hand CPUUtilization > 80% (TagName: other)",
                         rtype="EC2", rid="i-001")
        by_name = _alarm("[EC2] srv mem_used_percent > 80% (TagName: i-001)")
        idx = AlarmIndex([renamed, by_name, {"AlarmName": "[RemediationDLQ] x"}])
        assert sorted(idx.find_names("i-001", "EC2")) == sorted([renamed["AlarmName"], by_name["AlarmName"]])
        assert idx.find_names("i-002", "EC2") == []


# ── 가드: 이름 파싱 정규식 재유입 방지 (AGENTS.md AP-23) ─────────────────────

_ALLOWED = {"common/alarm_identity.py", "common/alarm_naming.py", "common/alarm_search.py"}
_TAGNAME_REGEX_LITERAL = re.compile(r"TagName:\\s")   # 정규식 리터럴 안의 'TagName:\s'


def test_no_alarm_name_regex_outside_identity_module():
    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith("tests/") or rel in _ALLOWED or ".venv" in rel:
            continue
        if _TAGNAME_REGEX_LITERAL.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == [], f"alarm-name regex outside common/alarm_identity.py: {offenders}"
