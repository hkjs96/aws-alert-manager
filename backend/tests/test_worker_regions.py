"""정기 워커의 리전 순회 (2026-10).

워커가 고객 계정으로 전환할 때 리전을 안 넘겨 람다 리전(us-east-1)만 봤다 — 첫 실고객의 서울 리소스는 고아 정리·
알람 동기화·임계치 알림이 정기 실행에서 빠졌다(화면 토글만 리소스 리전을 써서 동작했다).
"""

from unittest.mock import MagicMock, patch

import pytest

FAKE_CREDS = {"AccessKeyId": "a", "SecretAccessKey": "s", "SessionToken": "t"}


class TestWorkerRegions:
    def test_account_regions_plus_virginia_in_order(self):
        from daily_monitor import lambda_handler as lh
        acc = [{"account_id": "771283576189", "regions": ["ap-northeast-2", "ap-northeast-1"]}]
        with patch.object(lh, "_resolve_accounts_for_inventory", return_value=acc):
            assert lh._worker_regions("771283576189", "arn:r") == ["ap-northeast-2", "ap-northeast-1", "us-east-1"]

    def test_virginia_listed_once(self):
        from daily_monitor import lambda_handler as lh
        acc = [{"account_id": "1", "regions": ["us-east-1", "ap-northeast-2"]}]
        with patch.object(lh, "_resolve_accounts_for_inventory", return_value=acc):
            assert lh._worker_regions("1", "arn:r") == ["us-east-1", "ap-northeast-2"]

    def test_unresolvable_regions_keep_the_old_scope(self):
        from botocore.exceptions import NoCredentialsError
        from daily_monitor import lambda_handler as lh
        with patch.object(lh, "_resolve_accounts_for_inventory", side_effect=NoCredentialsError()):
            assert lh._worker_regions("self", "") == ["us-east-1"]


def _run(handler_name, event, regions):
    from daily_monitor import lambda_handler as lh
    entered = []
    with patch.object(lh, "_worker_regions", return_value=regions), \
         patch.object(lh, "_sync_inventory", return_value={"discovered": 0}), \
         patch.object(lh, "_switch_account_session", return_value=FAKE_CREDS) as switch, \
         patch.object(lh, "_enter_region", side_effect=lambda c, a, r: entered.append((c, r))), \
         patch.object(lh, "_restore_lambda_session") as restore, \
         patch.object(lh, "_notify_unregistered_regions", return_value=[]), \
         patch.object(lh, "_cleanup_orphan_alarms", return_value=[]) as cleanup, \
         patch.object(lh, "_collect_from_all_collectors", return_value=[]) as collect, \
         patch.object(lh, "_put_monitor_run_start"), patch.object(lh, "_mark_stale_runs"), \
         patch.object(lh, "_finish_monitor_run"), patch.object(lh, "_monitor_run_history_table"):
        result = getattr(lh, handler_name)(event, None)
    return result, entered, switch, restore, cleanup, collect


@pytest.mark.parametrize("handler_name", ["lambda_handler", "_handle_tag_reconcile"])
class TestEveryRegionIsVisited:
    def test_each_region_gets_cleanup_and_collection_with_one_assume_role(self, handler_name):
        event = {"account_id": "771283576189", "role_arn": "arn:aws:iam::771283576189:role/R"}
        if handler_name == "_handle_tag_reconcile":
            event["mode"] = "tag_reconcile"
        result, entered, switch, restore, cleanup, collect = _run(
            handler_name, event, ["ap-northeast-2", "us-east-1"])
        switch.assert_called_once()
        assert entered == [(FAKE_CREDS, "ap-northeast-2"), (FAKE_CREDS, "us-east-1")]
        assert cleanup.call_count == 2 and collect.call_count == 2
        restore.assert_called_once()
        assert result["regions"] == ["ap-northeast-2", "us-east-1"]

    def test_own_account_changes_region_without_assume_role(self, handler_name):
        result, entered, switch, restore, *_ = _run(handler_name, {"account_id": "self"}, ["ap-northeast-2", "us-east-1"])
        switch.assert_not_called()
        assert entered == [(None, "ap-northeast-2"), (None, "us-east-1")]
        restore.assert_called_once()


def test_session_is_restored_even_when_a_region_pass_fails():
    from daily_monitor import lambda_handler as lh
    with patch.object(lh, "_worker_regions", return_value=["ap-northeast-2"]), \
         patch.object(lh, "_sync_inventory", return_value={}), \
         patch.object(lh, "_enter_region"), \
         patch.object(lh, "_reconcile_region_pass", side_effect=RuntimeError("boom")), \
         patch.object(lh, "_restore_lambda_session") as restore:
        with pytest.raises(RuntimeError):
            lh._handle_tag_reconcile({"mode": "tag_reconcile", "account_id": "self"}, None)
    restore.assert_called_once()


class TestSeoulPassFindsSeoulAlarms:
    """2026-10-12 07:32 첫 서울 순회 사고 — 바스티온 알람 4개가 지워지고 재생성이 실패했다."""

    def test_resource_region_follows_the_switched_default_session(self):
        import boto3
        from common.collectors.generic import session_region
        try:
            boto3.setup_default_session(region_name="ap-northeast-2")
            assert session_region() == "ap-northeast-2"
        finally:
            boto3.setup_default_session()

    @pytest.mark.parametrize("client_region, expected", [
        ("ap-northeast-2", ""),                                         # 다른 리전 토픽은 붙이지 않는다
        ("us-east-1", "arn:aws:sns:us-east-1:949501913924:alert"),    # 같은 리전이면 그대로
    ])
    def test_alarm_actions_only_use_a_topic_in_the_alarms_region(self, client_region, expected):
        from common.alarm_builder import _same_region_topic
        cw = MagicMock()
        cw.meta.region_name = client_region
        assert _same_region_topic(cw, "arn:aws:sns:us-east-1:949501913924:alert") == expected

    def test_seoul_alarm_is_created_without_the_virginia_topic(self):
        import os
        from common.alarm_manager import create_alarms_for_resource
        cw = MagicMock()
        cw.meta.region_name = "ap-northeast-2"
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_paginator.return_value.paginate.return_value = [{"MetricAlarms": []}]
        cw.list_metrics.return_value = {"Metrics": []}
        with patch.dict(os.environ, {"SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:949501913924:alert"}), \
             patch("common.alarm_builder._get_disk_dimensions", return_value=[]):
            create_alarms_for_resource("i-1", "EC2", {"Monitoring": "on", "Name": "bastion"}, cw=cw)
        puts = [c.kwargs for c in cw.put_metric_alarm.call_args_list]
        assert puts and all(p["AlarmActions"] == [] for p in puts)
