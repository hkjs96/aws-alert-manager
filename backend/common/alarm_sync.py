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
from common.dimension_builder import _get_disk_dimensions
from common.alarm_registry import _get_alarm_defs, get_dynamic_eval_policy
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
    tag_suffix_to_disk_path,
)
from common.threshold_resolver import (
    _resolve_free_local_storage_threshold,
    _resolve_free_memory_threshold,
)

logger = logging.getLogger("common.alarm_manager")


# put_metric_alarm으로 우리가 설정하는 값 중, 알람 정의에서 바뀌면 기존 알람도
# 다시 만들어야 하는 필드. (CloudWatch 응답 키, alarm_def 키, 미지정 시 기본값)
#
# Namespace/MetricName/Dimensions는 여기서 비교하지 않는다. 그것들은 설정이 아니라
# 알람의 정체성이라, 바뀌면 애초에 같은 알람으로 매칭되지 않는다.
_CONFIG_FIELDS: tuple[tuple[str, str, object | None], ...] = (
    ("Statistic", "stat", None),
    ("Period", "period", None),
    ("EvaluationPeriods", "evaluation_periods", None),
    ("ComparisonOperator", "comparison", None),
    ("TreatMissingData", "treat_missing_data", "notBreaching"),
    ("DatapointsToAlarm", "datapoints_to_alarm", None),
)


def _config_drift(alarm_info: dict, alarm_def: dict) -> list[str]:
    """알람 정의와 실제 알람 설정이 어긋난 필드 목록을 반환한다.

    임계치만 비교하면 evaluation_periods·period·statistic 같은 설정을 레지스트리에서
    바꿔도 이미 만들어진 알람에는 영원히 반영되지 않는다. 정의와 실제가 말없이
    갈라지는 것을 막기 위해 우리가 설정하는 필드는 모두 비교한다.
    """
    drifted = []
    for cw_key, def_key, default in _CONFIG_FIELDS:
        expected = alarm_def.get(def_key, default)
        if expected is None:
            # 우리가 put_metric_alarm에 넘기지 않는 필드는 비교 대상이 아니다.
            continue
        if alarm_info.get(cw_key) != expected:
            drifted.append(cw_key)
    return drifted


def _sync_disk_alarms(
    key_to_alarm: dict[str, dict],
    resource_id: str,
    resource_tags: dict,
    result: dict[str, list],
    *,
    alarm_def: dict | None = None,
    cw=None,
) -> bool:
    """Disk 알람 동기화. 변경 필요 시 True 반환."""
    disk_alarms = {k: v for k, v in key_to_alarm.items() if k.startswith("Disk_")}
    if not disk_alarms:
        result["created"].append("disk_used_percent")
        return True

    extra_paths = {
        tag_suffix_to_disk_path(k[len("Threshold_Disk_"):])
        for k in resource_tags
        if k.startswith("Threshold_Disk_") and k != "Threshold_Disk_root"
    }
    expected_paths = {
        next((d["Value"] for d in dims if d["Name"] == "path"), "/")
        for dims in _get_disk_dimensions(resource_id, extra_paths or None, cw=cw)
    }
    existing_paths = {
        next((d["Value"] for d in alarm.get("Dimensions", []) if d["Name"] == "path"), "/")
        for alarm in disk_alarms.values()
    }
    missing_paths = expected_paths - existing_paths
    if missing_paths:
        logger.info("Missing disk alarms for %s paths: %s", resource_id, sorted(missing_paths))
        result["created"].append("disk_used_percent")
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
            continue

        drifted = _config_drift(alarm_info, alarm_def) if alarm_def else []
        if drifted:
            logger.info("Disk alarm %s config drift: %s", name, ", ".join(drifted))
            result["updated"].append(name)
            changed = True
            continue

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
    metric_key = metric

    if is_threshold_off(resource_tags, metric_key):
        return False

    if metric_key == "FreeableMemory":
        threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
    elif metric_key == "FreeLocalStorage":
        threshold, cw_threshold = _resolve_free_local_storage_threshold(resource_tags)
    else:
        threshold = get_threshold(resource_tags, metric_key)
        transform = alarm_def.get("transform_threshold")
        cw_threshold = transform(threshold) if transform else threshold

    cw_name = alarm_def.get("metric_name") or metric
    alarm_info = key_to_alarm.get(metric_key) or key_to_alarm.get(cw_name)
    if not alarm_info:
        result["created"].append(metric)
        return True

    name = alarm_info["AlarmName"]
    existing_thr = alarm_info.get("Threshold", 0)
    if abs(existing_thr - cw_threshold) > 0.001:
        result["updated"].append(name)
        return True

    drifted = _config_drift(alarm_info, alarm_def)
    if drifted:
        logger.info("Alarm %s config drift: %s", name, ", ".join(drifted))
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
        metric_key = metric
        if not is_threshold_off(resource_tags, metric_key):
            continue
        cw_name = alarm_def.get("metric_name") or metric
        alarm_info = key_to_alarm.get(metric_key) or key_to_alarm.get(cw_name)
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
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    hardcoded_keys = (
        {d["metric"] for d in alarm_defs}
        | {d.get("metric_name") or d["metric"] for d in alarm_defs}
    )

    dynamic_tags = _parse_threshold_tags(resource_tags, resource_type)

    existing_dynamic: dict[str, dict] = {
        mk: info for mk, info in key_to_alarm.items()
        if mk not in hardcoded_keys and not mk.startswith("Disk_")
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

        # 임계치 드리프트 + 평가 정책 드리프트 모두 재생성 대상.
        # DatapointsToAlarm 미설정 알람은 CloudWatch가 EvaluationPeriods와
        # 같은 값으로 취급하므로 그 기준으로 비교한다.
        eval_periods, datapoints = get_dynamic_eval_policy(mk)
        existing_ep = alarm_info.get("EvaluationPeriods")
        existing_dp = alarm_info.get("DatapointsToAlarm") or existing_ep
        drifted = (
            abs(existing_thr - tag_thr) > 0.001
            or existing_ep != eval_periods
            or existing_dp != datapoints
        )
        if drifted:
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

    if "disk_used_percent" in result["created"] or not existing_names:
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags, **_fwd)
        result["created"] = created
    else:
        for alarm_name in result["updated"]:
            _recreate_alarm_by_name(alarm_name, resource_id, resource_type, resource_tags, **_fwd)
        for metric in result["created"]:
            if metric != "disk_used_percent":
                _create_single_alarm(metric, resource_id, resource_type, resource_tags, **_fwd)
