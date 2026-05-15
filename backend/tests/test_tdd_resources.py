import json
import pytest
from unittest.mock import patch, MagicMock

def _event(method: str, path: str, qs=None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "queryStringParameters": qs or {},
    }

class TestResourcesTDD:
    @patch("api_handler.routes.resources.get_resources_from_alarms")
    @patch("api_handler.routes.resources.discover_resources")
    @patch("api_handler.routes.resources.scan_all")
    def test_should_display_resource_even_without_alarms(self, mock_scan, mock_discover, mock_get_from_alarms):
        """
        [RED] AWS Discovery에는 존재하지만 알람이 없는 리소스가 목록에 표시되는지 검증.
        현재 list_resources는 get_resources_from_alarms만 호출하므로, 
        discovery에만 있는 리소스는 누락될 것이며 이 테스트는 실패해야 한다.
        """
        # 1. 알람 기반 리소스는 비어 있음
        mock_get_from_alarms.return_value = {"items": [], "total": 0, "page": 1, "page_size": 25}
        
        # 2. 하지만 AWS Discovery에서는 1개가 발견됨
        mock_discover.return_value = [{
            "resource_id": "i-tdd-no-alarm",
            "name": "tdd-test",
            "type": "EC2",
            "account_id": "123456789012",
            "region": "ap-northeast-2",
            "monitoring": False,
            "status": "active"
        }]
        mock_scan.return_value = [] # DB는 비어있음
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        body = json.loads(resp["body"])
        items = body["items"]
        
        # 검증: discovery에서 발견된 리소스가 1개 있어야 함
        assert len(items) == 1, "알람이 없더라도 Discovery에서 발견된 리소스는 표시되어야 합니다."
        assert items[0]["id"] == "i-tdd-no-alarm"
