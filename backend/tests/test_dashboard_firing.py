"""대시보드 '알람 발생' — 고객이 만든 알람도 세고, 우리 알람과 나눈다."""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from api_handler import cw_helper

OURS = {"AlarmName": "[EC2] web CPUUtilization > 80% (TagName: i-1)",
        "AlarmDescription": 'Auto-created by AWS Monitoring Engine | {"metric_key":"CPU","resource_id":"i-1","resource_type":"EC2"}'}
CUSTOMER = {"AlarmName": "TEST-ALARM", "AlarmDescription": ""}
ACCOUNTS = [{"customer_id": "HOME", "account_id": "771283576189", "connection_status": "connected"},
            {"customer_id": "HOME", "account_id": "222222222222", "connection_status": "failed"}]


@pytest.fixture(autouse=True)
def _no_cache():
    cw_helper._FIRING_CACHE.clear()
    yield
    cw_helper._FIRING_CACHE.clear()


def test_splits_ours_and_customer_across_regions():
    acct = {**ACCOUNTS[0], "regions": ["ap-northeast-2", "us-east-1"]}
    by_region = {"ap-northeast-2": [OURS, CUSTOMER], "us-east-1": [dict(CUSTOMER)]}
    with patch.object(cw_helper, "_load_registered_accounts", return_value=[acct]), \
            patch.object(cw_helper, "identify_alarm", side_effect=lambda a: object() if a is OURS else None), \
            patch.object(cw_helper, "_firing_in", side_effect=lambda a, r: by_region[r]) as fi:
        assert cw_helper.count_firing_alarms("HOME") == {"ours": 1, "customer": 2}
        assert fi.call_count == 2
        # 60초 안의 재호출은 캐시 — 계정을 다시 묻지 않는다
        assert cw_helper.count_firing_alarms("HOME") == {"ours": 1, "customer": 2}
        assert fi.call_count == 2


def test_lookup_failure_returns_none_and_is_not_cached():
    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "AssumeRole")
    with patch.object(cw_helper, "_load_registered_accounts", return_value=ACCOUNTS[:1]), \
            patch.object(cw_helper, "_firing_in", side_effect=err):
        assert cw_helper.count_firing_alarms("HOME") is None
    assert cw_helper._FIRING_CACHE == {}


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
