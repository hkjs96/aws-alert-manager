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
