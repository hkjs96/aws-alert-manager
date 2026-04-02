"""
Alarm Sync — 알람 동기화 로직

Daily Monitor용 알람 동기화를 전담한다.
하드코딩 메트릭 동기화, Disk 알람 동기화, 동적 알람 동기화, off 태그 처리를 포함한다.
"""

import logging

from botocore.exceptions import ClientError

import common._clients as _clients
from common.alarm_builder import (
    _create_dynamic_alarm,
    _create_single_alarm,
    _recreate_alarm_by_name,
    _resolve_metric_key,
)
from common.alarm_registry import _get_alarm_defs, _get_hardcoded_metric_keys
from common.alarm_search import (
    _delete_alarm_names,
    _delete_all_alarms_for_resource,
    _describe_alarms_batch,
    _find_alarms_for_resource,
)
from common.tag_resolver import (
    disk_path_to_tag_suffix,
    get_threshold,
    is_threshold_off,
)
from common.threshold_resolver import (
    _resolve_free_local_storage_threshold,
    _resolve_free_memory_threshold,
)

logger = logging.getLogger("common.alarm_manager")


def _sync_disk_alarms(
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
) -> bool:
    """Disk 알람 동기화. 변경 필요 시 True 반환."""
    disk_alarms = {k: v for k, v in key_to_alarm.items() if k.startswith("Disk")}
    if not disk_alarms:
        result["created"].append("Disk")
        return True

    changed = False
    for _mk, alarm_info in disk_alarms.items():
        name = alarm_info["AlarmName"]
        existing_thr = alarm_info.get("Threshold", 0)
        path = next(
            (d["Value"] for d in alarm_info.get("Dimensions", []) if d["Name"] == "path"),
            "/",
        )
        suffix = disk_path_to_tag_suffix(path)
        if is_threshold_off(resource_tags, f"Disk_{suffix}"):
            continue
        expected_thr = get_threshold(resource_tags, f"Disk_{suffix}")
        if abs(existing_thr - expected_thr) > 0.001:
            result["updated"].append(name)
            changed = True
        else:
            result["ok"].append(name)
    return changed


def _sync_standard_alarms(
    alarm_def: dict,
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
) -> bool:
    """표준 메트릭 알람 동기화. 변경 필요 시 True 반환."""
    metric = alarm_def["metric"]
    if is_threshold_off(resource_tags, metric):
        return False

    if metric == "FreeMemoryGB":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    elif metric == "FreeLocalStorageGB":
        threshold, cw_threshold = _resolve_free_local_storage_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    alarm_info = key_to_alarm.get(metric)
    if not alarm_info:
        result["created"].append(metric)
        return True

    name = alarm_info["AlarmName"]
    existing_thr = alarm_info.get("Threshold", 0)
    if abs(existing_thr - cw_threshold) > 0.001:
        result["updated"].append(name)
        return True

    result["ok"].append(name)
    return False


def _sync_off_hardcoded(
    alarm_defs: list[dict],
    key_to_alarm: dict[str, dict],
    resource_tags: dict,
    result: dict[str, list],
    *,
    cw=None,
) -> None:
    """하드코딩 알람 off 체크: 기존 알람이 있으면 삭제 + deleted 추가."""
    cw = cw or _clients._get_cw_client()
    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        if not is_threshold_off(resource_tags, metric):
            continue
        alarm_info = key_to_alarm.get(metric)
        if not alarm_info:
            continue
        name = alarm_info["AlarmName"]
        for lst_key in ("ok", "updated", "created"):
            if name in result[lst_key]:
                result[lst_key].remove(name)
            if metric in result[lst_key]:
                result[lst_key].remove(metric)
        try:
            cw.delete_alarms(AlarmNames=[name])
            logger.info(
                "Deleted alarm %s for %s: threshold set to off",
                name, metric,
            )
        except ClientError as e:
            logger.error("Failed to delete off alarm %s: %s", name, e)
            continue
        result["deleted"].append(name)


def _sync_dynamic_alarms(
    key_to_alarm: dict[str, dict],
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    result: dict[str, list],
    *,
    cw=None,
) -> None:
    """동적 알람 동기화: 생성/삭제/업데이트."""
    # Avoid circular import: _parse_threshold_tags lives in alarm_manager
    from common.alarm_manager import _get_sns_alert_arn, _parse_threshold_tags

    cw = cw or _clients._get_cw_client()
    sns_arn = _get_sns_alert_arn()
    resource_name = resource_tags.get("Name", "")
    hardcoded_keys = _get_hardcoded_metric_keys(resource_type, resource_tags)

    dynamic_tags = _parse_threshold_tags(resource_tags, resource_type)

    existing_dynamic: dict[str, dict] = {
        mk: info for mk, info in key_to_alarm.items()
        if mk not in hardcoded_keys and not mk.startswith("Disk")
    }

    for metric_name, (threshold, comparison) in dynamic_tags.items():
        if metric_name in existing_dynamic:
            continue
        _create_dynamic_alarm(
            resource_id, resource_type, resource_name,
            metric_name, threshold, cw, sns_arn, result["created"],
            comparison=comparison,
        )

    for mk, alarm_info in existing_dynamic.items():
        name = alarm_info["AlarmName"]
        if mk not in dynamic_tags:
            _delete_alarm_names(cw, [name])
            result["deleted"].append(name)
            continue
        existing_thr = alarm_info.get("Threshold", 0)
        tag_thr, tag_comparison = dynamic_tags[mk]
        if abs(existing_thr - tag_thr) > 0.001:
            _delete_alarm_names(cw, [name])
            _create_dynamic_alarm(
                resource_id, resource_type, resource_name,
                mk, tag_thr, cw, sns_arn, result["created"],
                comparison=tag_comparison,
            )
            result["updated"].append(name)
        else:
            result["ok"].append(name)


def _apply_sync_changes(
    result: dict[str, list],
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    existing_names: list[str],
    *,
    cw=None,
) -> None:
    """동기화 결과에 따라 알람 재생성/생성 적용."""
    from common.alarm_manager import create_alarms_for_resource

    _fwd: dict = {"cw": cw} if cw is not None else {}
    cw = cw or _clients._get_cw_client()

    if "Disk" in result["created"] or not existing_names:
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags, **_fwd)
        result["created"] = created
    else:
        for alarm_name in result["updated"]:
            _recreate_alarm_by_name(alarm_name, resource_id, resource_type, resource_tags, **_fwd)
        for metric in result["created"]:
            if metric != "Disk":
                _create_single_alarm(metric, resource_id, resource_type, resource_tags, **_fwd)
