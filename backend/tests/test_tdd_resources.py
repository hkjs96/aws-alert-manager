import json
import pytest
from unittest.mock import patch, MagicMock

def _event(method: str, path: str, qs=None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "queryStringParameters": qs or {},
    }

class TestResourcesTDD:
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    @patch.dict("os.environ", {"RESOURCE_INVENTORY_TABLE": "test-inventory"})
    def test_should_display_resource_even_without_alarms(self, mock_scan, mock_table):
        """
        DynamoDB 스냅샷에는 존재하지만 알람이 없는 리소스가 목록에 표시되는지 검증.
        """
        # DynamoDB 스냅샷에는 1개 존재
        mock_scan.return_value = [{
            "resource_id": "i-tdd-no-alarm",
            "name": "tdd-test",
            "type": "EC2",
            "account_id": "123456789012",
            "region": "ap-northeast-2",
            "monitoring": False,
            "status": "active",
            "inventory_source": "aws",
            "entity_type": "resource",
        }]
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        body = json.loads(resp["body"])
        items = body["items"]
        
        # 검증: DynamoDB에서 조회된 리소스가 1개 있어야 함
        assert len(items) == 1, "알람이 없더라도 DynamoDB 스냅샷에 있는 리소스는 표시되어야 합니다."
        assert items[0]["id"] == "i-tdd-no-alarm"
        assert items[0]["alarm_count"] == 0

