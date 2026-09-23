"""
알람 인벤토리 스냅숏 행 — 데일리 런과 API 토글이 **같은 모양**으로 쓴다.

리소스 상세 화면의 알람 표(`GET /resources/{id}/alarms`)는 CloudWatch를 직접 읽지 않고 인벤토리의 알람 행
(`entity_type=alarm`)을 읽는다. 2026-09-23까지 그 행은 데일리 런·시간 단위 정합 런만 썼다 — 그래서 콘솔에서
모니터링을 켜도 알람은 바로 생기는데 화면의 표는 최대 한 시간 비어 있었다(첫 실고객 토글에서 발견). 이제 토글도
같은 빌더로 행을 쓴다. 빌더가 한 곳에 있어야 두 경로의 행이 어긋나지 않는다.
"""

from __future__ import annotations

from common.alarm_builder import resolve_alarm_severity
from common.alarm_identity import identify_alarm


def snapshot_key(alarm_arn: str) -> str:
    """인벤토리 표에서 알람 행의 파티션 키."""
    return f"alarm#{alarm_arn}"


def build_alarm_item(alarm: dict, db_key: str, account: str, arn_parts: list[str]) -> dict:
    alarm_name = alarm["AlarmName"]
    region = arn_parts[3] if len(arn_parts) > 3 and arn_parts[3] else alarm.get("_region", "unknown")
    
    # resource = 정본(Full) ID → 프론트 링크 /resources/{token}와 대시보드의 인벤토리
    # 조인이 ALB/NLB/TG에서도 맞는다. tag_name은 이름의 short ID (표시·레거시 매칭용).
    identity = identify_alarm(alarm)
    if identity is not None:
        res_type, res_id, tag_name = identity.resource_type, identity.resource_id, identity.tag_name
    else:
        res_type, res_id, tag_name = "", alarm_name, ""

    tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
    severity = resolve_alarm_severity(alarm)
    ts = alarm.get("StateUpdatedTimestamp")
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")

    return {
        "resource_id": db_key,
        "account_id": account,
        "alarm_name": alarm_name,
        "arn": alarm.get("AlarmArn", ""),
        "entity_type": "alarm",
        "state": alarm.get("StateValue", ""),
        "metric": alarm.get("MetricName", ""),
        "namespace": alarm.get("Namespace", ""),
        "comparison": alarm.get("ComparisonOperator", ""),
        "threshold": str(alarm.get("Threshold", "0")),
        "severity": severity,
        "time": ts_str,
        "region": region,
        "type": res_type,
        "resource": res_id,
        "tag_name": tag_name,
        "inventory_source": "alarms",
        "tags": tags,
        "status": "active",
        "period": alarm.get("Period"),
        "evaluation_periods": alarm.get("EvaluationPeriods"),
        "datapoints_to_alarm": alarm.get("DatapointsToAlarm"),
        "treat_missing_data": alarm.get("TreatMissingData"),
        "statistic": alarm.get("Statistic"),
    }


def alarm_snapshot_items(alarms: list[dict]) -> list[dict]:
    """describe_alarms 항목 → 인벤토리 알람 행. 이 엔진이 관리하는 포맷의 알람만 통과시킨다.

    단순 "[" 접두사 필터는 CFN이 만든 `[RemediationDLQ]` 같은 인프라 알람이나 고객이 비슷한 이름으로 만든
    알람까지 유령 행으로 넣는다 — 리소스를 역추출할 수 있는 관리 포맷(`identify_alarm`)만 쓴다.
    """
    items: list[dict] = []
    for alarm in alarms:
        if identify_alarm(alarm) is None:
            continue
        arn = alarm.get("AlarmArn", "")
        if not arn:
            continue
        arn_parts = arn.split(":")
        account = arn_parts[4] if len(arn_parts) > 4 and arn_parts[4] else alarm.get("_account_id", "unknown")
        items.append(build_alarm_item(alarm, snapshot_key(arn), account, arn_parts))
    return items
