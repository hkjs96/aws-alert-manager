"""/resources/{id}/thresholds — 리소스별 임계치·판단 방식(M/N) 조회와 편집 (docs/specs/bulk-alarm-config).

값은 고객 리소스의 태그에 둔다: `Threshold_{지표}=값|off`, `Threshold_{지표}_Eval=M/N`. 해제는 태그 삭제다.
쓰기는 모니터링 토글과 같은 세션(고객 계정 역할)으로 하고, 바뀐 태그로 그 리소스의 알람을 바로 맞춘다.
단일 편집과 벌크(화면이 리소스마다 PUT을 보낸다)가 이 경로 하나를 쓴다.

디스크 경로별 지표는 경로마다 따로 해석돼 여기서 다루지 않는다.
"""

import json
import logging
import math

from botocore.exceptions import ClientError

from api_handler.authz import scope_for
from api_handler.routes import resources as res
from common import SUPPORTED_RESOURCE_TYPES, customer_thresholds
from common.alarm_manager import sync_alarms_for_resource
from common.alarm_registry import _METRIC_DISPLAY, _get_alarm_defs, eval_locked
from common.tag_resolver import (
    _LEGACY_TAG_MAP,
    eval_tag_key,
    get_eval_override,
    get_threshold,
    is_threshold_off,
    parse_eval,
)

logger = logging.getLogger(__name__)

_ACCESS_DENIED = ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation")


def get_resource_thresholds(event: dict) -> dict:
    resource, error = _load(event)
    if error:
        return error
    try:
        tags = res._live_resource_tags(resource)
    except (ClientError, RuntimeError) as exc:
        return res._err(500, "AWS_ERROR", str(exc))
    return res._ok({
        "resource_id": _rid(resource),
        "resource_type": resource.get("type"),
        "monitoring": bool(resource.get("monitoring")),
        "metrics": describe(resource.get("type", ""), tags, res._customer_defaults_for(resource)),
    })


def update_resource_thresholds(event: dict) -> dict:
    resource, error = _load(event)
    if error:
        return error
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return res._err(400, "INVALID_BODY", "Invalid JSON body")
    try:
        to_set, to_remove = plan_tags(resource.get("type", ""), body)
    except ValueError as exc:
        return res._err(400, "VALIDATION_ERROR", str(exc))
    if not to_set and not to_remove:
        return res._err(400, "VALIDATION_ERROR", "nothing to change")

    try:
        live = res._live_resource_tags(resource)
        _write_tags(resource, to_set, to_remove)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _ACCESS_DENIED:
            return _role_update_required(exc)
        return res._err(500, "AWS_ERROR", str(exc))
    except PermissionError as exc:
        return _role_update_required(exc)
    except (RuntimeError, ValueError) as exc:
        return res._err(500, "AWS_ERROR", str(exc))

    after = {k: v for k, v in live.items() if k not in to_remove}
    after.update(to_set)
    alarms_synced = _sync_alarms(resource, after)
    return res._ok({
        "resource_id": _rid(resource),
        "status": "updated",
        "tags_written": to_set,
        "tags_removed": sorted(to_remove),
        "alarms_synced": alarms_synced,
        "metrics": describe(resource.get("type", ""), after, res._customer_defaults_for(resource)),
    })


# ── 순수 로직(테스트 대상) ─────────────────────────────────────────


def editable_defs(resource_type: str, tags: dict) -> list[dict]:
    """편집할 수 있는 정의 — 디스크 경로별 지표는 뺀다."""
    return [d for d in _get_alarm_defs(resource_type, tags) if not d.get("dynamic_dimensions")]


def describe(resource_type: str, tags: dict, defaults: dict | None) -> list[dict]:
    """지표마다 지금 값·출처·기본값·판단 방식. 화면의 단일 편집과 벌크 영향 보기가 이걸 읽는다."""
    merged = customer_thresholds.apply(tags, defaults)
    system_defs = {d["metric"]: d for d in editable_defs(resource_type, {})}
    out = []
    for d in editable_defs(resource_type, merged):
        metric = d["metric"]
        label, direction, unit = _METRIC_DISPLAY.get(metric, (metric, ">", ""))
        base = system_defs.get(metric, d)
        override = get_eval_override(tags, metric)
        off = is_threshold_off(tags, metric)
        out.append({
            "metric": metric,
            "label": label,
            "direction": direction,
            "unit": unit,
            "statistic": d.get("stat"),
            "period": d.get("period"),
            "off": off,
            "value": None if off else get_threshold(merged, metric),
            "source": customer_thresholds.source_of(tags, defaults, metric),
            "customer_default": (defaults or {}).get(metric),
            "system_default": get_threshold({}, metric),
            "eval": _fmt_eval(d),
            "eval_source": "resource" if override and not eval_locked(d) else "system",
            "eval_default": _fmt_eval(base),
            "eval_locked": eval_locked(d),
        })
    return out


def plan_tags(resource_type: str, body: dict) -> tuple[dict[str, str], set[str]]:
    """요청 → (쓸 태그, 지울 태그 키). 잘못된 요청은 ValueError.

    body: `{"set": {지표: 값|"off"}, "eval": {지표: "M/N"|null}, "clear": [지표]}`
    - `clear`: 개별 임계치 해제(레거시 이름 태그도 함께 지운다 — 남으면 그게 이긴다).
    - `eval` 값 null: 판단 방식을 시스템 기본으로 되돌린다.
    """
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource type: {resource_type}")
    defs = {d["metric"]: d for d in editable_defs(resource_type, {})}
    set_values = body.get("set") or {}
    evals = body.get("eval") or {}
    clears = body.get("clear") or []
    if not isinstance(set_values, dict) or not isinstance(evals, dict) or not isinstance(clears, list):
        raise ValueError("set/eval must be objects and clear a list")

    to_set: dict[str, str] = {}
    to_remove: set[str] = set()
    for metric in [*set_values, *evals, *clears]:
        if metric not in defs:
            raise ValueError(f"Metric '{metric}' cannot be edited for {resource_type}")
    for metric, raw in set_values.items():
        to_set[f"Threshold_{metric}"] = _threshold_value(metric, raw)
        legacy = _LEGACY_TAG_MAP.get(metric)
        if legacy:
            to_remove.add(f"Threshold_{legacy}")
    for metric in clears:
        if metric in set_values:
            raise ValueError(f"Metric '{metric}' is both set and cleared")
        to_remove.add(f"Threshold_{metric}")
        legacy = _LEGACY_TAG_MAP.get(metric)
        if legacy:
            to_remove.add(f"Threshold_{legacy}")
    for metric, raw in evals.items():
        legacy = _LEGACY_TAG_MAP.get(metric)
        if legacy:
            to_remove.add(eval_tag_key(legacy))
        if raw is None:
            to_remove.add(eval_tag_key(metric))
            continue
        if eval_locked(defs[metric]):
            raise ValueError(f"Evaluation of '{metric}' is fixed (availability metric)")
        if parse_eval(raw) is None:
            raise ValueError(f"Evaluation for '{metric}' must be M/N with 1 <= M <= N <= 10")
        to_set[eval_tag_key(metric)] = str(raw).strip()
    to_remove -= set(to_set)
    return to_set, to_remove


def _threshold_value(metric: str, raw) -> str:
    if isinstance(raw, str) and raw.strip().lower() == "off":
        return "off"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Threshold for '{metric}' must be a number or 'off'") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Threshold for '{metric}' must be a positive number")
    return str(int(value)) if value == int(value) else str(value)


def _fmt_eval(alarm_def: dict) -> str:
    n = int(alarm_def.get("evaluation_periods") or 1)
    m = int(alarm_def.get("datapoints_to_alarm") or n)
    return f"{m}/{n}"


# ── AWS ──────────────────────────────────────────────────────────


def _load(event: dict):
    resource_id = res._path_id(event)
    if not resource_id:
        return None, res._err(400, "MISSING_PARAM", "resource_id is required")
    try:
        resource = res._find_inventory_resource(resource_id)
    except ClientError as exc:
        return None, res._err(500, "AWS_ERROR", str(exc))
    if not resource or not scope_for(event).allows_item(resource):
        return None, res._not_found(resource_id)
    return resource, None


def _rid(resource: dict) -> str:
    return resource.get("resource_id") or resource.get("id") or ""


def _tagging_client(resource: dict):
    session, region, _ = res._resource_aws_session(resource)
    if session is not None:
        return session.client("resourcegroupstaggingapi", region_name=region)
    return res._get_tagging_client_for_region(region)


def _write_tags(resource: dict, to_set: dict[str, str], to_remove: set[str]) -> None:
    arn = res._resource_arn_for_tagging(resource)
    if not arn:
        raise ValueError(f"Cannot resolve tagging ARN for {resource.get('type')} {_rid(resource)}")
    client = _tagging_client(resource)
    if to_set:
        _raise_failed(arn, client.tag_resources(ResourceARNList=[arn], Tags=to_set))
    if to_remove:
        _raise_failed(arn, client.untag_resources(ResourceARNList=[arn], TagKeys=sorted(to_remove)))


def _raise_failed(arn: str, resp: dict) -> None:
    """RGT는 권한 거부도 예외가 아니라 FailedResourcesMap으로 돌려준다."""
    failed = (resp.get("FailedResourcesMap") or {}).get(arn)
    if not failed:
        return
    code = failed.get("ErrorCode", "")
    message = failed.get("ErrorMessage", "")
    if "AccessDenied" in code or "AccessDenied" in message or "not authorized" in message:
        raise PermissionError(message or code)
    raise RuntimeError(f"Failed to tag {arn}: {code} {message}".strip())


def _role_update_required(exc) -> dict:
    logger.warning("Threshold tag write denied: %s", exc)
    return res._err(403, "ROLE_UPDATE_REQUIRED",
                    "이 계정의 역할이 Threshold_* 태그를 쓸 수 없습니다 — 고객사 온보딩 스택을 최신 템플릿으로 업데이트하세요.")


def _sync_alarms(resource: dict, tags_after: dict) -> bool:
    """바뀐 태그로 알람을 바로 맞춘다. 모니터링이 꺼진 리소스는 태그만 바꾼다. 실패해도 다음 정합 런이 맞춘다."""
    if not resource.get("monitoring"):
        return False
    tags = {**tags_after, "Monitoring": "on", **res._collector_tags(resource)}
    tags = customer_thresholds.apply(tags, res._customer_defaults_for(resource))
    try:
        session, region, _ = res._resource_aws_session(resource)
        cw = (session.client("cloudwatch", region_name=region)
              if session is not None else res._get_cw_client_for_region(region))
        sync_alarms_for_resource(_rid(resource), resource.get("type"), tags, cw=cw)
        res._refresh_alarm_rows(resource, cw)
    except (ClientError, ValueError, RuntimeError, KeyError) as exc:
        logger.warning("Immediate alarm sync after threshold edit failed for %s: %s", _rid(resource), exc)
        return False
    return True
