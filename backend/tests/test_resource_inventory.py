import json
import os
from unittest.mock import MagicMock, patch
import pytest

def _event(method: str, path: str, body=None, qs=None, path_params=None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": qs or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
    }

@pytest.fixture
def mock_db_env(monkeypatch):
    monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")
    monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")
    monkeypatch.setenv("CUSTOMERS_TABLE", "test-customers")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")

class TestResourceInventoryLogic:

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_merges_aws_and_db(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        # 1. AWS Discovery returns 1 resource
        mock_discover.return_value = [{
            "resource_id": "i-aws-01",
            "name": "aws-instance",
            "type": "EC2",
            "account_id": "123456789012",
            "region": "ap-northeast-2",
            "customer_id": "cust-01",
            "monitoring": True,
            "status": "active"
        }]
        
        # 2. DB scan returns 1 different resource (stale)
        # mock_scan is called twice: once for accounts, once for inventory
        mock_scan.side_effect = [
            [{"account_id": "123456789012", "customer_id": "cust-01"}], # accounts
            [{ # inventory
                "resource_id": "i-db-01",
                "account_id": "123456789012",
                "name": "stale-instance",
                "type": "EC2",
                "status": "active"
            }]
        ]
        
        # 3. Alarm overlay returns alarm for both
        mock_overlay.return_value = {
            "i-aws-01": {"count": 1, "critical": 1, "warning": 0},
            "i-db-01": {"count": 2, "critical": 0, "warning": 2}
        }
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        items = body["items"]
        
        assert len(items) == 2
        
        # Check AWS discovered item
        aws_item = next(i for i in items if i["id"] == "i-aws-01")
        assert aws_item["inventory_source"] == "aws"
        assert aws_item["account"] == "123456789012"
        assert aws_item["account_id"] == "123456789012"
        assert aws_item["status"] == "active"
        assert aws_item["alarm_count"] == 1
        assert aws_item["alarms"]["critical"] == 1
        assert aws_item["persisted"] == False
        
        # Check DB stale item
        db_item = next(i for i in items if i["id"] == "i-db-01")
        assert db_item["inventory_source"] == "db"
        assert db_item["status"] == "missing"
        assert db_item["alarm_count"] == 2
        assert db_item["alarms"]["warning"] == 2
        assert db_item["persisted"] == True

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_discovers_current_account_when_accounts_empty(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        mock_discover.return_value = [{
            "resource_id": "i-live-01",
            "name": "live-instance",
            "type": "EC2",
            "account_id": "self",
            "region": "us-east-1",
            "monitoring": True,
            "status": "active",
        }]
        mock_scan.side_effect = [[], []]
        mock_overlay.return_value = {}

        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["id"] == "i-live-01"
        assert body["items"][0]["inventory_source"] == "aws"
        mock_discover.assert_called_once_with([{
            "account_id": "self",
            "regions": ["us-east-1"],
        }])

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_identifies_orphan_alarms(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        """AWS나 DB에는 없지만 알람만 존재하는 경우 orphan_candidate 후보로 표시해야 한다."""
        # 1. AWS/DB 모두 비어 있음
        mock_discover.return_value = []
        mock_scan.side_effect = [
            [{"account_id": "123", "regions": ["ap-ne2"]}], # accounts
            [] # inventory
        ] 
        
        # 2. 알람은 존재함 (i-orphan-01)
        mock_overlay.return_value = {
            "i-orphan-01": {"count": 1, "critical": 0, "warning": 1}
        }
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        body = json.loads(resp["body"])
        items = body["items"]
        
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "i-orphan-01"
        assert item["status"] == "orphan_candidate"
        assert item["inventory_source"] == "alarms"

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_filters_correctly(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        """resource_type 필터링이 정확히 동작해야 한다."""
        mock_discover.return_value = [
            {"resource_id": "i-01", "name": "e1", "type": "EC2", "account_id": "1", "region": "r1", "monitoring": True, "status": "active"},
            {"resource_id": "db-01", "name": "r1", "type": "RDS", "account_id": "1", "region": "r1", "monitoring": True, "status": "active"}
        ]
        mock_scan.side_effect = [[{"account_id": "1"}], []]
        mock_overlay.return_value = {}
        
        from api_handler.routes.resources import list_resources
        # EC2만 필터링
        resp = list_resources(_event("GET", "/resources", qs={"resource_type": "EC2"}))
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["type"] == "EC2"

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_identifies_orphan_alarms(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        """AWS나 DB에는 없지만 알람만 존재하는 경우 orphan_alarm 후보로 표시해야 한다."""
        # 1. AWS/DB 모두 비어 있음
        mock_discover.return_value = []
        mock_scan.side_effect = [[], []] 
        
        # 2. 알람은 존재함 (i-orphan-01)
        mock_overlay.return_value = {
            "i-orphan-01": {"count": 1, "critical": 0, "warning": 1}
        }
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        body = json.loads(resp["body"])
        items = body["items"]
        
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "i-orphan-01"
        assert item["status"] == "orphan_candidate"
        assert item["inventory_source"] == "alarms"

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_list_resources_keeps_unmonitored_discovered_resources(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        """Monitoring 태그 값이 비어도 실제 존재하는 리소스는 목록에 표시한다."""
        mock_discover.return_value = [{
            "resource_id": "i-unmonitored",
            "name": "unmonitored",
            "type": "EC2",
            "account_id": "1",
            "region": "us-east-1",
            "customer_id": "cust-01",
            "monitoring": False,
            "status": "active",
        }]
        mock_scan.side_effect = [[{"account_id": "1", "regions": ["us-east-1"]}], []]
        mock_overlay.return_value = {}

        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["id"] == "i-unmonitored"
        assert body["items"][0]["monitoring"] is False

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_get_resource_resolves_discovered_resource_by_name_without_alarms(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        mock_discover.return_value = [{
            "resource_id": "i-01",
            "name": "web-01",
            "type": "EC2",
            "account_id": "123",
            "customer_id": "cust-01",
            "region": "us-east-1",
            "monitoring": False,
            "status": "active",
        }]
        mock_scan.side_effect = [[{"account_id": "123", "regions": ["us-east-1"]}], []]
        mock_overlay.return_value = {}

        from api_handler.routes.resources import get_resource
        resp = get_resource(_event("GET", "/resources/web-01", path_params={"id": "web-01"}))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "i-01"
        assert body["name"] == "web-01"
        assert body["monitoring"] is False
        assert body["alarm_count"] == 0

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    @patch("api_handler.routes.resources.get_alarm_overlay")
    def test_get_resource_resolves_persisted_resource_by_id_without_alarms(self, mock_overlay, mock_scan, mock_discover, mock_db_env):
        mock_discover.return_value = []
        mock_scan.side_effect = [
            [{"account_id": "123", "regions": ["us-east-1"]}],
            [{
                "resource_id": "i-02",
                "name": "db-only",
                "type": "EC2",
                "account_id": "123",
                "customer_id": "cust-01",
                "region": "us-east-1",
                "monitoring": False,
                "status": "active",
            }],
        ]
        mock_overlay.return_value = {}

        from api_handler.routes.resources import get_resource
        resp = get_resource(_event("GET", "/resources/i-02", path_params={"id": "i-02"}))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "i-02"
        assert body["name"] == "db-only"
        assert body["inventory_source"] == "db"
        assert body["monitoring"] is False

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_sync_resources_discovers_current_account_when_accounts_empty(self, mock_scan, mock_table_func, mock_discover, mock_db_env):
        mock_discover.return_value = [{
            "resource_id": "i-live-01",
            "account_id": "self",
            "name": "live-instance",
            "type": "EC2",
            "region": "us-east-1",
            "monitoring": True,
        }]
        mock_scan.return_value = []
        mock_table = MagicMock()
        mock_table_func.return_value = mock_table

        from api_handler.routes.resources import sync_resources
        resp = sync_resources(_event("POST", "/resources/sync"))

        assert resp["statusCode"] == 200
        assert mock_table.put_item.called
        mock_discover.assert_called_once_with([{
            "account_id": "self",
            "regions": ["us-east-1"],
        }])

    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_sync_resources_updates_db(self, mock_scan, mock_table_func, mock_discover, mock_db_env):
        mock_discover.return_value = [{
            "resource_id": "i-01",
            "account_id": "123",
            "customer_id": "cust-01",
            "name": "res-01",
            "type": "EC2",
            "region": "ap-ne2",
            "monitoring": True
        }]
        mock_scan.return_value = [{"account_id": "123", "customer_id": "cust-01"}]
        mock_table = MagicMock()
        mock_table_func.return_value = mock_table
        
        from api_handler.routes.resources import sync_resources
        resp = sync_resources(_event("POST", "/resources/sync"))
        
        assert resp["statusCode"] == 200
        assert mock_table.put_item.called
        assert json.loads(resp["body"])["discovered"] == 1

    @patch("api_handler.routes.resources._get_ec2_client_for_region")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_update_resource_monitoring_sets_ec2_tag_and_inventory(self, mock_scan, mock_table_func, mock_ec2_func, mock_db_env):
        mock_scan.return_value = [{
            "resource_id": "i-01",
            "account_id": "123",
            "type": "EC2",
            "region": "us-east-1",
            "monitoring": False,
        }]
        mock_table = MagicMock()
        mock_table_func.return_value = mock_table
        mock_ec2 = MagicMock()
        mock_ec2_func.return_value = mock_ec2

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/i-01/monitoring", body={"monitoring": True}, path_params={"id": "i-01"})
        )

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["monitoring"] is True
        mock_ec2.create_tags.assert_called_once_with(
            Resources=["i-01"],
            Tags=[{"Key": "Monitoring", "Value": "on"}],
        )
        mock_table.update_item.assert_called_once_with(
            Key={"resource_id": "i-01", "account_id": "123"},
            UpdateExpression="SET monitoring = :monitoring",
            ExpressionAttributeValues={":monitoring": True},
        )

    @patch("api_handler.routes.resources.scan_all")
    def test_update_resource_monitoring_rejects_non_ec2(self, mock_scan, mock_db_env):
        mock_scan.return_value = [{"resource_id": "bucket-01", "type": "S3"}]

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/bucket-01/monitoring", body={"monitoring": True}, path_params={"id": "bucket-01"})
        )

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["code"] == "UNSUPPORTED_RESOURCE_TYPE"
