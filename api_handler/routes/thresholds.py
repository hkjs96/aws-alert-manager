"""
/thresholds/{resource_type} 엔드포인트

GET /thresholds/{type}?customer_id=X
    → alarm_registry의 시스템 기본값 + DynamoDB 고객사 오버라이드 병합

PUT /thresholds/{type}
    body: {"customer_id": "...", "overrides": [{"metric_key": "CPU", "customer_override": 90}, ...]}
    → DynamoDB에 저장 (customer_override=null이면 해당 항목 삭제)
"""

import json
from decimal import Decimal

from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from api_handler.db import threshold_overrides_table

# alarm_registry에서 리소스 타입별 기본 임계치 가져오기
# HARDCODED_DEFAULTS: {"CPU": 80, "Memory": 80, ...}
# _METRIC_DISPLAY: {"CPU": ("CPUUtilization", ">", "%"), ...}
# _get_alarm_defs(resource_type): alarm def 리스트

import sys
import os

# common 모듈 경로 추가 (Lambda Layer에서는 /opt/python/에 위치)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))

try:
    from common.alarm_registry import _get_alarm_defs, _METRIC_DISPLAY
    from common import HARDCODED_DEFAULTS
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False
    _get_alarm_defs = None  # type: ignore
    _METRIC_DISPLAY = {}
    HARDCODED_DEFAULTS = {}


def get_system_defaults(resource_type: str) -> list[dict]:
    """리소스 타입별 시스템 기본 임계치 목록 반환."""
    if not _REGISTRY_AVAILABLE or _get_alarm_defs is None:
        return []

    try:
        alarm_defs = _get_alarm_defs(resource_type, {})
    except Exception:
        return []

    seen: set[str] = set()
    result = []
    for d in alarm_defs:
        key = d.get("metric_key") or d.get("metric", "")
        if not key or key in seen:
            continue
        seen.add(key)

        cw_metric = d.get("metric_name") or d.get("metric", key)
        display = (
            _METRIC_DISPLAY.get(key)
            or _METRIC_DISPLAY.get(cw_metric, (cw_metric, ">", ""))
        )
        _, direction, unit = display
        default_val = HARDCODED_DEFAULTS.get(key, HARDCODED_DEFAULTS.get(cw_metric, 0))

        result.append({
            "metric_key": key,
            "system_default": float(d.get("threshold", default_val)),
            "customer_override": None,
            "unit": unit,
            "direction": direction,
        })
    return result


def get_thresholds(event: dict) -> dict:
    resource_type = (event.get("pathParameters") or {}).get("type", "")
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "")

    defaults = get_system_defaults(resource_type)
    if not defaults:
        return _ok([])

    # DynamoDB에서 고객사 오버라이드 조회
    if customer_id:
        scope_id = f"customer_id:{customer_id}"
        try:
            table = threshold_overrides_table()
            resp = table.query(
                KeyConditionExpression=Key("scope_id").eq(scope_id)
            )
            overrides = {item["metric_key"]: item["threshold_value"] for item in resp.get("Items", [])}
        except ClientError:
            overrides = {}

        # 오버라이드 병합
        for item in defaults:
            raw = overrides.get(item["metric_key"])
            item["customer_override"] = float(raw) if raw is not None else None

    return _ok(defaults)


def put_thresholds(event: dict) -> dict:
    resource_type = (event.get("pathParameters") or {}).get("type", "")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")

    customer_id = (body.get("customer_id") or "").strip()
    if not customer_id:
        return _err(400, "MISSING_PARAM", "customer_id가 필요합니다")

    overrides: list[dict] = body.get("overrides", [])
    scope_id = f"customer_id:{customer_id}"
    table = threshold_overrides_table()
    saved = 0

    for override in overrides:
        metric_key = (override.get("metric_key") or "").strip()
        if not metric_key:
            continue

        val = override.get("customer_override")
        try:
            if val is None:
                # None → 오버라이드 삭제
                table.delete_item(Key={"scope_id": scope_id, "metric_key": metric_key})
            else:
                table.put_item(Item={
                    "scope_id": scope_id,
                    "metric_key": metric_key,
                    "resource_type": resource_type,
                    "threshold_value": Decimal(str(val)),
                })
            saved += 1
        except ClientError as e:
            import logging
            logging.getLogger(__name__).error(
                "Failed to save threshold %s/%s: %s", scope_id, metric_key, e
            )

    return _ok({"saved": saved, "resource_type": resource_type, "customer_id": customer_id})


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
