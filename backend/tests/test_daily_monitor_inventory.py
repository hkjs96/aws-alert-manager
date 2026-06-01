"""
daily_monitor.lambda_handler — ResourceInventoryTable sync 단위 테스트

_sync_inventory / _resolve_accounts_for_inventory / _sanitize_inventory_item
세 함수의 동작을 검증한다.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


_ENV = {
    "ENVIRONMENT": "test",
    "SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:123456789012:test-alerts",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
}


# ──────────────────────────────────────────────
# _sanitize_inventory_item
# ──────────────────────────────────────────────


class TestSanitizeInventoryItem:
    def test_strips_tags_and_arn(self):
        from daily_monitor.lambda_handler import _sanitize_inventory_item

        item = _sanitize_inventory_item({
            "resource_id": "i-001",
            "account_id": "123",
            "name": "srv",
            "type": "EC2",
            "region": "us-east-1",
            "customer_id": "cust-01",
            "monitoring": True,
            "status": "active",
            "tags": {"Monitoring": "on", "Name": "srv"},
            "arn": "arn:aws:lambda:...",
        })

        assert "tags" not in item
        assert "arn" not in item
        assert item["resource_id"] == "i-001"
        assert item["customer_id"] == "cust-01"
        assert item["monitoring"] is True

    def test_empty_customer_id_excluded(self):
        from daily_monitor.lambda_handler import _sanitize_inventory_item

        item = _sanitize_inventory_item({
            "resource_id": "i-001",
            "account_id": "123",
            "customer_id": "",
            "type": "EC2",
        })

        assert "customer_id" not in item

    def test_none_customer_id_excluded(self):
        from daily_monitor.lambda_handler import _sanitize_inventory_item

        item = _sanitize_inventory_item({
            "resource_id": "i-001",
            "account_id": "123",
            "customer_id": None,
            "type": "EC2",
        })

        assert "customer_id" not in item

    def test_defaults_applied(self):
        from daily_monitor.lambda_handler import _sanitize_inventory_item

        item = _sanitize_inventory_item({"resource_id": "i-001", "account_id": "123"})

        assert item["status"] == "active"
        assert item["monitoring"] is False
        assert item["name"] == ""


# ──────────────────────────────────────────────
# _resolve_accounts_for_inventory
# ──────────────────────────────────────────────


class TestResolveAccountsForInventory:
    def test_single_account_mode_uses_sts(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        # RESOURCE_INVENTORY_TABLE은 set 안 함 → 영향 없음
        # ACCOUNTS_TABLE 미설정 → fallback path

        sts_client = MagicMock()
        sts_client.get_caller_identity.return_value = {"Account": "999888777666"}

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler.boto3.client", return_value=sts_client):
            accounts = lh._resolve_accounts_for_inventory("self", "")

        assert len(accounts) == 1
        assert accounts[0]["account_id"] == "999888777666"
        assert accounts[0]["role_arn"] == ""

    def test_sts_failure_returns_empty(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)

        sts_client = MagicMock()
        sts_client.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GetCallerIdentity",
        )

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler.boto3.client", return_value=sts_client):
            accounts = lh._resolve_accounts_for_inventory("", "")

        assert accounts == []

    def test_multi_account_with_table_metadata(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")

        ddb_table = MagicMock()
        ddb_table.query.return_value = {
            "Items": [{
                "account_id": "111122223333",
                "customer_id": "cust-99",
                "regions": ["ap-northeast-2", "us-west-2"],
            }]
        }
        ddb_resource = MagicMock()
        ddb_resource.Table.return_value = ddb_table

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler.boto3.resource", return_value=ddb_resource):
            accounts = lh._resolve_accounts_for_inventory(
                "111122223333",
                "arn:aws:iam::111122223333:role/AlarmManagerRole",
            )

        assert len(accounts) == 1
        assert accounts[0]["account_id"] == "111122223333"
        assert accounts[0]["role_arn"] == "arn:aws:iam::111122223333:role/AlarmManagerRole"
        assert accounts[0]["regions"] == ["ap-northeast-2", "us-west-2"]
        assert accounts[0]["customer_id"] == "cust-99"

    def test_table_miss_returns_fallback(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")

        ddb_table = MagicMock()
        ddb_table.query.return_value = {"Items": []}
        ddb_resource = MagicMock()
        ddb_resource.Table.return_value = ddb_table

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler.boto3.resource", return_value=ddb_resource):
            accounts = lh._resolve_accounts_for_inventory("444455556666", "")

        assert len(accounts) == 1
        assert accounts[0]["account_id"] == "444455556666"
        assert accounts[0]["regions"] == ["ap-northeast-2"]
        assert accounts[0]["customer_id"] == ""

    def test_table_query_error_returns_fallback(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")

        ddb_table = MagicMock()
        ddb_table.query.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "no table"}},
            "Query",
        )
        ddb_resource = MagicMock()
        ddb_resource.Table.return_value = ddb_table

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler.boto3.resource", return_value=ddb_resource):
            accounts = lh._resolve_accounts_for_inventory("444455556666", "")

        assert len(accounts) == 1
        assert accounts[0]["regions"] == ["ap-northeast-2"]


# ──────────────────────────────────────────────
# _sync_inventory
# ──────────────────────────────────────────────


class TestSyncInventory:
    def test_skipped_when_env_var_missing(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("RESOURCE_INVENTORY_TABLE", raising=False)

        from daily_monitor import lambda_handler as lh

        result = lh._sync_inventory("self", "")

        assert result["skipped"] == "no_inventory_table"
        assert result["synced"] == 0

    def test_writes_each_discovered_resource(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")

        discovered = [
            {"resource_id": "i-001", "account_id": "123", "type": "EC2",
             "name": "srv1", "region": "us-east-1", "customer_id": "cust-1",
             "monitoring": True, "status": "active",
             "tags": {"Monitoring": "on"}},
            {"resource_id": "i-002", "account_id": "123", "type": "EC2",
             "name": "srv2", "region": "us-east-1", "customer_id": "cust-1",
             "monitoring": False, "status": "active",
             "tags": {}},
        ]

        inv_table = MagicMock()
        inv_table.query.return_value = {"Items": []}
        ddb_resource = MagicMock()
        ddb_resource.Table.return_value = inv_table

        from daily_monitor import lambda_handler as lh

        with (
            patch("daily_monitor.lambda_handler._resolve_accounts_for_inventory",
                  return_value=[{"account_id": "123", "role_arn": "",
                                 "regions": ["us-east-1"], "customer_id": "cust-1"}]),
            patch("daily_monitor.lambda_handler.discover_resources", return_value=discovered),
            patch("daily_monitor.lambda_handler._fetch_alarms_for_accounts", return_value=[]),
            patch("daily_monitor.lambda_handler.boto3.resource", return_value=ddb_resource),
        ):
            result = lh._sync_inventory("123", "")

        assert result["discovered"] == 2
        assert result["synced"] == 2
        assert inv_table.put_item.call_count == 2
        # tags가 sanitize에서 빠졌는지 확인
        first_call = inv_table.put_item.call_args_list[0]
        assert "tags" not in first_call.kwargs["Item"]

    def test_no_accounts_returns_skipped(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")

        from daily_monitor import lambda_handler as lh

        with patch("daily_monitor.lambda_handler._resolve_accounts_for_inventory", return_value=[]):
            result = lh._sync_inventory("self", "")

        assert result["skipped"] == "no_account_metadata"

    def test_discover_error_returns_error(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")

        from daily_monitor import lambda_handler as lh

        with (
            patch("daily_monitor.lambda_handler._resolve_accounts_for_inventory",
                  return_value=[{"account_id": "123", "role_arn": "", "regions": ["us-east-1"]}]),
            patch("daily_monitor.lambda_handler.discover_resources",
                  side_effect=ClientError({"Error": {"Code": "X", "Message": "y"}}, "Describe")),
        ):
            result = lh._sync_inventory("123", "")

        assert result["error"] == "discover_failed"

    def test_skips_resources_missing_id_or_account(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")

        discovered = [
            {"resource_id": "", "account_id": "123", "type": "EC2"},  # 빈 ID
            {"resource_id": "i-002", "account_id": "", "type": "EC2"},  # 빈 account
            {"resource_id": "i-003", "account_id": "123", "type": "EC2"},
        ]

        inv_table = MagicMock()
        inv_table.query.return_value = {"Items": []}
        ddb_resource = MagicMock()
        ddb_resource.Table.return_value = inv_table

        from daily_monitor import lambda_handler as lh

        with (
            patch("daily_monitor.lambda_handler._resolve_accounts_for_inventory",
                  return_value=[{"account_id": "123", "role_arn": "", "regions": ["us-east-1"]}]),
            patch("daily_monitor.lambda_handler.discover_resources", return_value=discovered),
            patch("daily_monitor.lambda_handler._fetch_alarms_for_accounts", return_value=[]),
            patch("daily_monitor.lambda_handler.boto3.resource", return_value=ddb_resource),
        ):
            result = lh._sync_inventory("123", "")

        assert result["synced"] == 1


# ──────────────────────────────────────────────
# lambda_handler가 _sync_inventory를 호출하는지 확인
# ──────────────────────────────────────────────


class TestLambdaHandlerCallsInventory:
    def test_lambda_handler_invokes_sync_inventory(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)

        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = MagicMock()
        mock_collector.__name__ = "mock"
        mock_collector.collect_monitored_resources.return_value = []

        with (
            patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
            patch("daily_monitor.lambda_handler._sync_inventory",
                  return_value={"discovered": 5, "synced": 5}) as mock_sync,
            patch("daily_monitor.lambda_handler._switch_account_session"),
            patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
        ):
            result = lh.lambda_handler(
                {"account_id": "111122223333",
                 "role_arn": "arn:aws:iam::111122223333:role/AlarmManagerRole"},
                None,
            )

        mock_sync.assert_called_once_with(
            "111122223333",
            "arn:aws:iam::111122223333:role/AlarmManagerRole",
        )
        assert result["inventory_synced"]["discovered"] == 5

    def test_sync_inventory_runs_before_session_switch(self, monkeypatch):
        """세션 전환 전에 inventory sync가 실행되어야 메인 계정 DDB에 write 가능."""
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)

        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        call_order = []

        def fake_sync(*args, **kwargs):
            call_order.append("sync_inventory")
            return {"discovered": 0, "synced": 0}

        def fake_switch(*args, **kwargs):
            call_order.append("switch_session")

        mock_collector = MagicMock()
        mock_collector.__name__ = "mock"
        mock_collector.collect_monitored_resources.return_value = []

        with (
            patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
            patch("daily_monitor.lambda_handler._sync_inventory", side_effect=fake_sync),
            patch("daily_monitor.lambda_handler._switch_account_session", side_effect=fake_switch),
            patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
        ):
            lh.lambda_handler(
                {"account_id": "111122223333",
                 "role_arn": "arn:aws:iam::111122223333:role/AlarmManagerRole"},
                None,
            )

        assert call_order == ["sync_inventory", "switch_session"]

    def test_inventory_sync_error_does_not_abort_handler(self, monkeypatch):
        """inventory sync 실패해도 메인 monitoring 로직은 계속 진행."""
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)

        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = MagicMock()
        mock_collector.__name__ = "mock"
        mock_collector.collect_monitored_resources.return_value = []

        with (
            patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
            patch("daily_monitor.lambda_handler._sync_inventory",
                  side_effect=ClientError({"Error": {"Code": "X", "Message": "y"}}, "Op")),
            patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
        ):
            result = lh.lambda_handler({}, None)

        assert result["status"] == "ok"
        assert "error" in result["inventory_synced"]
