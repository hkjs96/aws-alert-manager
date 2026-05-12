"""
CloudWatch 조회 헬퍼.

알람 목록, 리소스 목록(알람명 파싱), 대시보드 통계 집계에 사용한다.
"""

import functools
import re

import boto3
from botocore.exceptions import ClientError

import logging

logger = logging.getLogger(__name__)

# [EC2] label metric >threshold (TagName: resource_id)
_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")


@functools.lru_cache(maxsize=None)
def _get_cw():
    return boto3.client("cloudwatch")


def list_alarms(alarm_name_prefix: str = "[", state_value: str | None = None) -> list[dict]:
    """관리 대상 알람 목록 조회. ManagedBy=AlarmManager 태그 기준으로 필터."""
    cw = _get_cw()
    kwargs: dict = {
        "AlarmTypes": ["MetricAlarm"],
        "AlarmNamePrefix": alarm_name_prefix,
    }
    if state_value:
        kwargs["StateValue"] = state_value

    alarms = []
    try:
        paginator = cw.get_paginator("describe_alarms")
        for page in paginator.paginate(**kwargs):
            alarms.extend(page.get("MetricAlarms", []))
    except ClientError as e:
        logger.error("CloudWatch describe_alarms failed: %s", e)
        raise
    return alarms


def _parse_alarm_arn(alarm_arn: str) -> tuple[str, str]:
    """AlarmArn에서 (region, account_id) 추출. 파싱 실패 시 ("unknown", "unknown")."""
    parts = alarm_arn.split(":")
    region = parts[3] if len(parts) > 3 and parts[3] else "unknown"
    account_id = parts[4] if len(parts) > 4 and parts[4] else "unknown"
    return region, account_id


def extract_resource_from_alarm(alarm_name: str) -> tuple[str, str] | None:
    """알람 이름에서 (resource_type, tag_name) 추출. 매칭 실패 시 None."""
    m = _ALARM_NAME_RE.match(alarm_name)
    if m:
        return m.group(1), m.group(2)
    return None


def get_dashboard_stats(customer_id: str | None = None, account_id: str | None = None) -> dict:
    """대시보드 통계 집계. 현재는 단일 계정 기준."""
    try:
        all_alarms = list_alarms()
    except ClientError:
        return {"monitored_count": 0, "active_alarms": 0, "unmonitored_count": 0, "account_count": 0}

    # 리소스 집합 추출 (알람명 파싱)
    resources: set[tuple[str, str]] = set()
    active_alarms = 0
    for alarm in all_alarms:
        result = extract_resource_from_alarm(alarm["AlarmName"])
        if result:
            resources.add(result)
        if alarm.get("StateValue") == "ALARM":
            active_alarms += 1

    return {
        "monitored_count": len(resources),
        "active_alarms": active_alarms,
        "unmonitored_count": 0,  # Phase 2: DynamoDB 리소스 목록과 비교
        "account_count": 1,      # Phase 2: AccountsTable count
    }


def get_resources_from_alarms(
    page: int = 1,
    page_size: int = 25,
    resource_type: str | None = None,
    search: str | None = None,
) -> dict:
    """알람명 파싱으로 모니터링 중인 리소스 목록 구성."""
    try:
        all_alarms = list_alarms()
    except ClientError:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    # resource_type → tag_name → alarms 매핑
    resource_map: dict[tuple[str, str], dict] = {}
    for alarm in all_alarms:
        result = extract_resource_from_alarm(alarm["AlarmName"])
        if not result:
            continue
        rtype, tag_name = result
        key = (rtype, tag_name)
        if key not in resource_map:
            region, account_id = _parse_alarm_arn(alarm.get("AlarmArn", ""))
            resource_map[key] = {
                "id": tag_name,
                "name": tag_name,
                "type": rtype,
                "account": account_id,
                "region": region,
                "monitoring": True,
                "alarms": {"critical": 0, "warning": 0},
            }
        if alarm.get("StateValue") == "ALARM":
            tags = alarm.get("Tags", {})
            sev = next((t["Value"] for t in tags if t["Key"] == "Severity"), "SEV-5")
            if sev in ("SEV-1", "SEV-2"):
                resource_map[key]["alarms"]["critical"] += 1
            else:
                resource_map[key]["alarms"]["warning"] += 1

    items = list(resource_map.values())

    # 필터링
    if resource_type:
        items = [r for r in items if r["type"] == resource_type]
    if search:
        lower = search.lower()
        items = [r for r in items if lower in r["id"].lower() or lower in r["name"].lower()]

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start: start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
