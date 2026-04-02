"""
Alarm Manager - CloudWatch Alarm 자동 생성/삭제/동기화 Facade

Monitoring=on 태그 감지 시 리소스 유형별 CloudWatch Alarm을 자동 생성하고,
태그 제거 시 삭제한다. 내부 로직은 책임별 모듈에 위임한다.

모듈 구조:
  alarm_registry   — 알람 정의 데이터, 매핑 테이블
  alarm_naming     — 알람 이름 생성, 메타데이터
  threshold_resolver — 임계치 해석
  dimension_builder — CloudWatch 디멘션 빌드
  alarm_search     — 알람 검색/삭제
  alarm_builder    — 알람 생성 (put_metric_alarm)
  alarm_sync       — 알람 동기화 (Daily Monitor)
"""

import logging
import math
import os
import re

from botocore.exceptions import ClientError

import common._clients as _clients
from common.tag_resolver import (
    disk_path_to_tag_suffix,
    get_threshold,
    is_threshold_off,
    tag_suffix_to_disk_path,
)

logger = logging.getLogger(__name__)

# Re-export shared CW client for backward compatibility
_get_cw_client = _clients._get_cw_client


def _get_sns_alert_arn() -> str:
    return os.environ.get("SNS_TOPIC_ARN_ALERT", "")


# ──────────────────────────────────────────────
# Re-exports (backward compatibility)
# ──────────────────────────────────────────────
from common.alarm_registry import (  # noqa: E402, F401
    _METRIC_DISPLAY,
    _EC2_ALARMS,
    _RDS_ALARMS,
    _ALB_ALARMS,
    _NLB_ALARMS,
    _TG_ALARMS,
    _AURORA_RDS_ALARMS,
    _AURORA_READER_REPLICA_LAG,
    _AURORA_ACU_UTILIZATION,
    _AURORA_SERVERLESS_CAPACITY,
    _get_aurora_alarm_defs,
    _DOCDB_ALARMS,
    _ELASTICACHE_ALARMS,
    _NATGW_ALARMS,
    _NLB_TG_EXCLUDED_METRICS,
    _get_alarm_defs,
    _HARDCODED_METRIC_KEYS,
    _NAMESPACE_MAP,
    _DIMENSION_KEY_MAP,
    _get_hardcoded_metric_keys,
    _metric_name_to_key,
)
from common.alarm_naming import (  # noqa: E402, F401
    _alarm_name,
    _pretty_alarm_name,
    _build_alarm_description,
    _parse_alarm_metadata,
    _shorten_elb_resource_id,
    _get_env,
)
from common.threshold_resolver import (  # noqa: E402, F401
    _resolve_free_memory_threshold,
    _resolve_free_local_storage_threshold,
    resolve_threshold,
)
from common.dimension_builder import (  # noqa: E402, F401
    _build_dimensions,
    _extract_elb_dimension,
    _resolve_tg_namespace,
    _resolve_metric_dimensions,
    _select_best_dimensions,
    _get_disk_dimensions,
)
from common.alarm_search import (  # noqa: E402, F401
    _find_alarms_for_resource,
    _delete_all_alarms_for_resource,
    _describe_alarms_batch,
    _delete_alarm_names,
)
from common.alarm_builder import (  # noqa: E402, F401
    _create_disk_alarms,
    _create_standard_alarm,
    _create_dynamic_alarm,
    _resolve_metric_key,
    _create_single_alarm,
    _recreate_alarm_by_name,
    _recreate_disk_alarm,
    _recreate_standard_alarm,
)
from common.alarm_sync import (  # noqa: E402, F401
    _sync_disk_alarms,
    _sync_standard_alarms,
    _sync_off_hardcoded,
    _sync_dynamic_alarms,
    _apply_sync_changes,
)


# AWS 태그 허용 문자 패턴 (메트릭 이름 부분)
_TAG_ALLOWED_CHARS = re.compile(
    r'^[a-zA-Z0-9 _.:/=+\-@]+$',
)


def _parse_threshold_tags(
    resource_tags: dict,
    resource_type: str,
) -> dict[str, tuple[float, str]]:
    """Threshold_* 태그에서 하드코딩 목록에 없는 동적 메트릭을 추출.

    태그 키 형식:
    - Threshold_{MetricName}={Value} → GreaterThanThreshold (기본)
    - Threshold_LT_{MetricName}={Value} → LessThanThreshold (낮을수록 위험)

    Returns:
        {metric_name: (threshold_value, comparison_operator)} 딕셔너리 (동적 메트릭만)
    """
    hardcoded = _get_hardcoded_metric_keys(resource_type, resource_tags)
    result: dict[str, tuple[float, str]] = {}

    for key, value in resource_tags.items():
        if not key.startswith("Threshold_"):
            continue
        if key.startswith("Threshold_Disk_"):
            continue
        if key in ("Threshold_FreeMemoryPct", "Threshold_FreeLocalStoragePct"):
            continue

        raw_metric = key[len("Threshold_"):]

        if raw_metric.startswith("LT_"):
            metric_name = raw_metric[len("LT_"):]
            comparison = "LessThanThreshold"
        else:
            metric_name = raw_metric
            comparison = "GreaterThanThreshold"

        if not metric_name:
            continue
        if metric_name in hardcoded or _metric_name_to_key(metric_name) in hardcoded:
            continue
        if len(key) > 128:
            logger.warning("Skipping dynamic tag %s: key exceeds 128 chars", key)
            continue
        if not _TAG_ALLOWED_CHARS.match(metric_name):
            logger.warning("Skipping dynamic tag %s: invalid characters in metric name", key)
            continue
        if value.strip().lower() == "off":
            logger.info("Skipping dynamic tag %s: alarm explicitly disabled (off)", key)
            continue
        try:
            val = float(value)
            if not math.isfinite(val) or val <= 0:
                logger.warning("Skipping dynamic tag %s=%s: not a positive number", key, value)
                continue
            result[metric_name] = (val, comparison)
        except (ValueError, TypeError):
            logger.warning("Skipping dynamic tag %s=%s: non-numeric value", key, value)

    return result


# ──────────────────────────────────────────────
# Public API (Facade)
# ──────────────────────────────────────────────

def create_alarms_for_resource(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    *,
    cw=None,
) -> list[str]:
    """리소스에 대한 CloudWatch Alarm을 생성한다."""
    _fwd: dict = {"cw": cw} if cw is not None else {}
    cw = cw or _clients._get_cw_client()
    sns_arn = _get_sns_alert_arn()
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    created: list[str] = []
    resource_name = resource_tags.get("Name", "")

    _delete_all_alarms_for_resource(resource_id, resource_type, **_fwd)

    for alarm_def in alarm_defs:
        if alarm_def.get("dynamic_dimensions") and alarm_def["metric"] == "Disk":
            disk_names = _create_disk_alarms(
                resource_id, resource_type, resource_name,
                resource_tags, alarm_def, cw, sns_arn,
            )
            created.extend(disk_names)
        else:
            if is_threshold_off(resource_tags, alarm_def["metric"]):
                logger.info(
                    "Skipping alarm for %s metric %s: threshold set to off",
                    resource_id, alarm_def["metric"],
                )
                continue
            name = _create_standard_alarm(
                alarm_def, resource_id, resource_type, resource_tags, cw,
            )
            if name:
                created.append(name)

    dynamic_metrics = _parse_threshold_tags(resource_tags, resource_type)
    for metric_name, (threshold, comparison) in dynamic_metrics.items():
        _create_dynamic_alarm(
            resource_id, resource_type, resource_name,
            metric_name, threshold, cw, sns_arn, created,
            comparison=comparison,
        )

    return created


def delete_alarms_for_resource(
    resource_id: str,
    resource_type: str,
    *,
    cw=None,
) -> list[str]:
    """리소스에 대한 CloudWatch Alarm을 삭제한다."""
    _fwd: dict = {"cw": cw} if cw is not None else {}
    return _delete_all_alarms_for_resource(resource_id, resource_type, **_fwd)


def sync_alarms_for_resource(
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
    *,
    cw=None,
) -> dict:
    """리소스의 알람이 현재 태그 임계치와 일치하는지 확인하고 불일치 시 업데이트."""
    _fwd: dict = {"cw": cw} if cw is not None else {}
    cw = cw or _clients._get_cw_client()
    result: dict[str, list] = {
        "created": [], "updated": [], "ok": [], "deleted": [],
    }

    existing_names = _find_alarms_for_resource(resource_id, resource_type, **_fwd)

    if not existing_names:
        created = create_alarms_for_resource(resource_id, resource_type, resource_tags, **_fwd)
        result["created"] = created
        return result

    alarm_map = _describe_alarms_batch(existing_names, **_fwd)

    key_to_alarm: dict[str, dict] = {}
    for alarm_info in alarm_map.values():
        mk = _resolve_metric_key(alarm_info)
        key_to_alarm.setdefault(mk, alarm_info)

    alarm_defs = _get_alarm_defs(resource_type, resource_tags)

    if not alarm_defs and existing_names:
        _delete_all_alarms_for_resource(resource_id, resource_type, **_fwd)
        return result

    needs_recreate = False
    for alarm_def in alarm_defs:
        metric = alarm_def["metric"]
        if alarm_def.get("dynamic_dimensions") and metric == "Disk":
            changed = _sync_disk_alarms(key_to_alarm, resource_tags, result)
            if changed:
                needs_recreate = True
        else:
            changed = _sync_standard_alarms(alarm_def, key_to_alarm, resource_tags, result)
            if changed:
                needs_recreate = True

    _sync_off_hardcoded(alarm_defs, key_to_alarm, resource_tags, result, **_fwd)
    _sync_dynamic_alarms(key_to_alarm, resource_id, resource_type, resource_tags, result, **_fwd)

    if needs_recreate:
        _apply_sync_changes(result, resource_id, resource_type, resource_tags, existing_names, **_fwd)

    return result
