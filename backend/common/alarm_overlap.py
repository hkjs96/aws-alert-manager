"""켜기 전 중복 점검 — 우리가 만들 알람과 고객이 이미 만든 알람이 같은 지표·디멘션을 보는가 (2026-10).

첫 실고객(HOME)은 직접 만든 알람이 165개다. 바스티온을 켜자 고객의 `STATUS_CHECK_FAILED`와 우리 `StatusCheckFailed > 0`이
같은 지표를 봐 장애 한 번에 알림이 두 번 갔다. 여기서는 **알려만 준다**(사용자 결정): 고객 알람의 이름·임계치가 달라
그것이 우리 알람을 대신하는지는 사람이 판단하고, 빼려면 기존 `Threshold_<지표>=off` 태그로 그 지표만 끈다.

판정: 같은 Namespace + MetricName + 디멘션 집합(순서 무관). 우리 알람(`identify_alarm`이 알아보는 것)은 제외.
디스크 알람은 경로별 디멘션이 실제 지표에서 정해져 미리 알 수 없어 건너뛴다. 고객 역할에는 `DescribeAlarmsForMetric`이
없어 그 리전의 알람을 `DescribeAlarms`로 받아 직접 비교한다.
"""

from __future__ import annotations

import logging

from botocore.exceptions import ClientError

from common.alarm_identity import identify_alarm
from common.alarm_registry import _get_alarm_defs
from common.dimension_builder import _build_dimensions

logger = logging.getLogger(__name__)

_SKIP_METRICS = {"disk_used_percent"}


def _dim_key(dimensions: list[dict]) -> frozenset:
    return frozenset((d["Name"], d["Value"]) for d in dimensions or [])


def _customer_alarms(cw) -> list[dict]:
    alarms: list[dict] = []
    for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["MetricAlarm"]):
        alarms.extend(a for a in page.get("MetricAlarms", []) if identify_alarm(a) is None)
    return alarms


def find_overlaps(resource_id: str, resource_type: str, resource_tags: dict, cw) -> list[dict]:
    """[{metric, namespace, metric_name, customer_alarms: [{name, threshold, comparison, state}]}] — 겹치는 것만."""
    planned = []
    for alarm_def in _get_alarm_defs(resource_type, resource_tags):
        metric = alarm_def.get("metric_key") or alarm_def["metric"]
        if metric in _SKIP_METRICS:
            continue
        try:
            dims = _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)
        except (KeyError, ValueError) as e:
            logger.info("Overlap check skipped for %s %s: %s", resource_type, metric, e)
            continue
        planned.append((metric, alarm_def["namespace"], alarm_def.get("metric_name") or alarm_def["metric"], _dim_key(dims)))
    if not planned:
        return []

    try:
        theirs = _customer_alarms(cw)
    except ClientError as e:
        logger.warning("Overlap check could not read alarms: %s", e)
        raise

    overlaps = []
    for metric, namespace, metric_name, dims in planned:
        hits = [a for a in theirs if a.get("Namespace") == namespace and a.get("MetricName") == metric_name
                and _dim_key(a.get("Dimensions")) == dims]
        if hits:
            overlaps.append({
                "metric": metric, "namespace": namespace, "metric_name": metric_name,
                "customer_alarms": [{"name": a["AlarmName"], "threshold": a.get("Threshold"),
                                     "comparison": a.get("ComparisonOperator"), "state": a.get("StateValue")}
                                    for a in hits],
            })
    return overlaps
