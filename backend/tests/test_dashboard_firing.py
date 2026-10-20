"""대시보드 '알람 발생' — 고객이 만든 알람도 세고, 우리 알람과 나눈다."""

from unittest.mock import patch

from botocore.exceptions import ClientError

from api_handler import cw_helper

OURS = {"AlarmName": "[EC2] web CPUUtilization > 80% (TagName: i-1)",
        "AlarmDescription": 'Auto-created by AWS Monitoring Engine | {"metric_key":"CPU","resource_id":"i-1","resource_type":"EC2"}'}
CUSTOMER = {"AlarmName": "TEST-ALARM", "AlarmDescription": ""}
ACCOUNTS = [{"customer_id": "HOME", "account_id": "771283576189", "connection_status": "connected"},
            {"customer_id": "HOME", "account_id": "222222222222", "connection_status": "failed"}]


def test_splits_ours_and_customer():
    with patch.object(cw_helper, "_load_registered_accounts", return_value=ACCOUNTS[:1]), \
            patch.object(cw_helper, "identify_alarm", side_effect=lambda a: object() if a is OURS else None), \
            patch.object(cw_helper, "list_alarms", return_value=[OURS, CUSTOMER, dict(CUSTOMER)]) as la:
        assert cw_helper.count_firing_alarms("HOME") == {"ours": 1, "customer": 2}
    # 이름 접두어 없이(고객 알람 포함) ALARM 상태만 조회한다
    assert la.call_args.kwargs["alarm_name_prefix"] == ""
    assert la.call_args.kwargs["state_value"] == "ALARM"


def test_lookup_failure_returns_none():
    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "DescribeAlarms")
    with patch.object(cw_helper, "_load_registered_accounts", return_value=ACCOUNTS[:1]), \
            patch.object(cw_helper, "list_alarms", side_effect=err):
        assert cw_helper.count_firing_alarms("HOME") is None


def test_connection_counts():
    with patch.object(cw_helper, "_load_registered_accounts", return_value=ACCOUNTS):
        assert cw_helper.count_account_connections("HOME") == {"connected": 1, "failed": 1}


def test_describe_without_prefix_omits_parameter():
    class Pager:
        def paginate(self, **kw):
            assert "AlarmNamePrefix" not in kw
            return [{"MetricAlarms": [CUSTOMER]}]

    class Cw:
        def get_paginator(self, _):
            return Pager()

    assert cw_helper._describe_alarms(Cw(), "", "ALARM") == [CUSTOMER]
