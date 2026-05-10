"""
/resources 엔드포인트

GET  /resources          → 리소스 목록 (페이지네이션, 필터)
POST /resources/sync     → 리소스 동기화 트리거
GET  /resources/{id}     → 단일 리소스 상세
GET  /resources/{id}/alarms  → 리소스의 알람 설정 목록
"""

import json
from botocore.exceptions import ClientError

from api_handler.cw_helper import get_resources_from_alarms, list_alarms, extract_resource_from_alarm


def list_resources(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)
    resource_type = qs.get("resource_type") or None
    search = qs.get("search") or None

    try:
        result = get_resources_from_alarms(
            page=page,
            page_size=page_size,
            resource_type=resource_type,
            search=search,
        )
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    return _ok(result)


def sync_resources(event: dict) -> dict:
    """
    리소스 동기화 트리거.
    Phase 1: daily_monitor Lambda를 직접 invoke 하거나 단순 응답 반환.
    Phase 2: SQS 비동기 작업으로 교체.
    """
    return _ok({
        "discovered": 0,
        "updated": 0,
        "removed": 0,
        "message": "동기화는 daily_monitor 스케줄 실행 시 자동 처리됩니다",
    })


def get_resource(event: dict) -> dict:
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    # resource_id(tag_name)로 알람 필터링
    resource_alarms = [
        a for a in alarms
        if _get_tag_name(a["AlarmName"]) == resource_id
    ]
    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"리소스 '{resource_id}'의 알람을 찾을 수 없습니다")

    resource_type = _get_resource_type(resource_alarms[0]["AlarmName"])
    active = sum(1 for a in resource_alarms if a.get("StateValue") == "ALARM")

    return _ok({
        "id": resource_id,
        "name": resource_id,
        "type": resource_type,
        "account": "current",
        "region": "ap-northeast-2",
        "monitoring": True,
        "alarms": {"critical": active, "warning": 0},
        "alarm_count": len(resource_alarms),
    })


def get_resource_alarms(event: dict) -> dict:
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    resource_alarms = [
        a for a in alarms
        if _get_tag_name(a["AlarmName"]) == resource_id
    ]

    configs = []
    for alarm in resource_alarms:
        tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
        configs.append({
            "alarm_name": alarm["AlarmName"],
            "metric_name": alarm.get("MetricName", ""),
            "namespace": alarm.get("Namespace", ""),
            "threshold": alarm.get("Threshold"),
            "comparison": alarm.get("ComparisonOperator", ""),
            "state": alarm.get("StateValue", ""),
            "severity": tags.get("Severity", "SEV-5"),
            "monitoring": True,
        })

    return _ok(configs)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

import re
_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")


def _get_tag_name(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(2) if m else ""


def _get_resource_type(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(1) if m else ""


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
