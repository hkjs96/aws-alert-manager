"""고객사 기본 임계치 — 리소스 개별값(태그)과 시스템 기본값 사이의 층.

우선순위: ① 리소스 `Threshold_*` 태그(개별값) → ② 고객사 기본값(설정 > 임계치) → ③ 시스템 기본값.

2026-10-26까지 ②는 저장만 되고 어디서도 읽지 않았다(설정 화면이 거짓 UI). 알람을 만드는 쪽은 전부
`resolve_threshold(alarm_def, resource_tags)`를 거치므로, ②를 **태그에 없는 지표만** 가상 태그로 끼워 넣어
같은 해석기를 그대로 쓴다. 실제 태그는 레거시 이름(`Threshold_CPU` 등)이나 `off`여도 항상 이긴다.

저장 형식(ThresholdOverridesTable): `scope_id="customer_id:{고객사}"`, `metric_key="{타입}#{지표}"`.
같은 지표 이름을 여러 타입이 쓰므로(EC2·RDS의 CPUUtilization) 타입을 키에 넣는다. 재보정 제안
(`scope_id="resource_id:…"`)과 같은 테이블이지만 접두어로 갈린다.

디스크 경로별 지표(`disk_used_percent(/data)`)는 경로마다 따로 해석돼 이 층을 거치지 않는다.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from botocore.exceptions import ClientError

from common.tag_resolver import _LEGACY_TAG_MAP

logger = logging.getLogger(__name__)

SCOPE_PREFIX = "customer_id:"


def scope_id(customer_id: str) -> str:
    return f"{SCOPE_PREFIX}{customer_id}"


def storage_key(resource_type: str, metric: str) -> str:
    return f"{resource_type}#{metric}"


def parse_items(items: list[dict]) -> dict[tuple[str, str], dict[str, float]]:
    """테이블 행 → {(고객사, 타입): {지표: 값}}. 고객사 기본값 행만, 잘못된 값은 버린다."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for item in items:
        sid = str(item.get("scope_id", ""))
        key = str(item.get("metric_key", ""))
        if not sid.startswith(SCOPE_PREFIX) or "#" not in key:
            continue
        rtype, _, metric = key.partition("#")
        try:
            value = float(item.get("threshold_value"))
        except (TypeError, ValueError):
            continue
        if value > 0 and rtype and metric:
            out.setdefault((sid[len(SCOPE_PREFIX):], rtype), {})[metric] = value
    return out


def load_all(table) -> dict[tuple[str, str], dict[str, float]]:
    """테이블 전체를 한 번 읽는다(고객사 수 × 지표 수 — 작다). 실패하면 빈 값: 시스템 기본값으로 동작한다."""
    items: list[dict] = []
    kwargs: dict = {}
    try:
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except ClientError as e:
        logger.error("customer threshold defaults unreadable: %s", e)
        return {}
    return parse_items(items)


def _has_own_tag(tags: dict, metric: str) -> bool:
    if f"Threshold_{metric}" in tags:
        return True
    legacy = _LEGACY_TAG_MAP.get(metric)
    return bool(legacy) and f"Threshold_{legacy}" in tags


def apply(tags: dict, defaults: dict[str, float] | None) -> dict:
    """태그에 없는 지표만 고객사 기본값을 가상 태그로 채운 **새** dict. 원본 태그는 건드리지 않는다."""
    if not defaults:
        return tags
    merged = dict(tags)
    for metric, value in defaults.items():
        if not _has_own_tag(tags, metric):
            merged[f"Threshold_{metric}"] = _fmt(value)
    return merged


def source_of(tags: dict, defaults: dict[str, float] | None, metric: str) -> str:
    """이 지표의 임계치가 어디서 오나 — "resource" | "customer" | "system". 영향도 표시용."""
    if _has_own_tag(tags, metric):
        return "resource"
    if defaults and metric in defaults:
        return "customer"
    return "system"


def _fmt(value) -> str:
    v = float(value if not isinstance(value, Decimal) else float(value))
    return str(int(v)) if v == int(v) else str(v)


def load_for_customer(table, customer_id: str) -> dict[str, dict[str, float]]:
    """한 고객사의 기본값 {타입: {지표: 값}} — Query 한 번. 실패·없음이면 {}(시스템 기본값으로 동작)."""
    if not customer_id or table is None:
        return {}
    from boto3.dynamodb.conditions import Key
    items: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": Key("scope_id").eq(scope_id(customer_id))}
    try:
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except ClientError as e:
        logger.error("customer threshold defaults unreadable for %s: %s", customer_id, e)
        return {}
    return {rtype: v for (cid, rtype), v in parse_items(items).items() if cid == customer_id}
