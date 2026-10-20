"""알람 목록 — 고객이 만든 알람도 CloudWatch에서 읽어 읽기 전용으로 보여 준다."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from api_handler.routes import alarms as route

CUSTOMER = {
    "AlarmName": "[EC2]EC2-AN2-HOME-PRD-WEBFIL-01A_NetworkIn_over", "AlarmArn": "arn:aws:cloudwatch:x:1:alarm:a",
    "AlarmDescription": "", "Namespace": "AWS/EC2", "MetricName": "NetworkIn",
    "Dimensions": [{"Name": "InstanceId", "Value": "i-0abc"}], "StateValue": "ALARM", "Threshold": 1e9,
    "StateUpdatedTimestamp": datetime(2026, 10, 20, tzinfo=timezone.utc),
    "_account_id": "771283576189", "_region": "ap-northeast-2",
}
OURS = {**CUSTOMER, "AlarmName": "[EC2] x CPUUtilization > 80% (TagName: i-1)"}


def _event(qs=None):
    return {"queryStringParameters": qs, "requestContext": {}}


def _run(handler, live, qs=None):
    with patch.object(route, "scan_all", return_value=[]), \
            patch.object(route, "resource_inventory_table", return_value="t"), \
            patch.object(route, "live_alarms", return_value=live), \
            patch.object(route, "identify_alarm", side_effect=lambda a: object() if a is OURS else None):
        return json.loads(handler(_event(qs))["body"])


def test_customer_alarm_is_listed_read_only():
    body = _run(route.list_alarms_handler, [CUSTOMER, OURS], {"state": "ALARM"})
    assert body["total"] == 1   # 우리 알람은 인벤토리 행으로 나오므로 여기서 다시 붙이지 않는다
    row = body["items"][0]
    assert row["source"] == "customer"
    assert (row["type"], row["resource"], row["account"], row["state"]) == ("EC2", "i-0abc", "771283576189", "ALARM")
    assert row["time"].startswith("2026-10-20")


def test_summary_counts_customer_alarms():
    assert _run(route.get_alarm_summary, [CUSTOMER])["alarm_count"] == 1


def test_lookup_failure_keeps_inventory_list():
    assert _run(route.list_alarms_handler, None)["total"] == 0
