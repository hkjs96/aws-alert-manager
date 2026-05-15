"""
/resources 엔드포인트 (TDD 원칙에 따라 이전 상태로 복구)
"""

import json
import logging
import os
from botocore.exceptions import ClientError
from api_handler.cw_helper import get_resources_from_alarms

logger = logging.getLogger(__name__)

def list_resources(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)
    resource_type = qs.get("resource_type") or None
    search = qs.get("search") or None

    try:
        # 기존 로직: 알람 기반으로만 리소스를 가져옴
        result = get_resources_from_alarms(
            page=page,
            page_size=page_size,
            resource_type=resource_type,
            search=search,
        )
    except ClientError as e:
        return {"statusCode": 500, "body": json.dumps({"code": "CW_ERROR", "message": str(e)})}

    return {"statusCode": 200, "body": json.dumps(result)}
