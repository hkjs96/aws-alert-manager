"""
/alert/channels · /alert/channel-types (tasks 2.2.1, design-notification-channels.md)

GET    /alert/channel-types           → 채널 유형 카탈로그 (설정 화면이 폼을 이걸로 그린다)
GET    /alert/channels                → 채널 목록 (?customer_id= 로 좁힘)
POST   /alert/channels                → 채널 등록. **전역 채널(customer_id 없음)은 관리자 전용**
PUT    /alert/channels/{id}           → 수정. 자격증명을 안 보내면 저장된 값이 유지된다
DELETE /alert/channels/{id}           → 삭제

**자격증명은 어떤 응답에도 나가지 않는다** — `channel_to_dict()`가 어댑터의 `secret` 선언을
읽어 값을 가린다(R6-8). 이 파일에서 항목을 직접 응답에 넣지 말 것. `api_handler`에는 스캔
결과를 그대로 돌려주는 코드가 12곳 있는데, 채널에서 그러면 슬랙 웹훅 URL이 목록으로 샌다.

**전역 채널을 관리자 전용으로 두는 이유:** 고객사 지정 없이 만들면 모든 고객사의 알림을 받는다.
전역 정비창(alert_policy)과 같은 폭발 반경이라 같은 기준을 적용한다.
"""

import json
import logging
import os

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from api_handler.db import notification_channel_table, scan_all
from api_handler.identity import admin_enforced, current_email, is_admin
from common import notification_adapters as adapters
from common.notification_channel import (
    MATCH_FIELDS,
    MAX_CHANNELS_PER_CUSTOMER,
    ChannelError,
    channel_from_item,
    channel_to_dict,
    channel_to_item,
    storage_key,
    validate_channel,
)

logger = logging.getLogger(__name__)


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str, ensure_ascii=False)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status,
            "body": json.dumps({"code": code, "message": message}, ensure_ascii=False)}


def _body(event: dict) -> dict:
    try:
        parsed = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        raise ChannelError("요청 본문이 JSON 형식이 아닙니다") from None
    if not isinstance(parsed, dict):
        raise ChannelError("요청 본문이 객체가 아닙니다")
    return parsed


def _customer_id(event: dict, body: dict | None = None) -> str:
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("customer_id")
    if raw is None and body is not None:
        raw = body.get("customer_id")
    return str(raw or "").strip()


def _forbidden(event: dict, what: str) -> dict | None:
    if admin_enforced() and not is_admin(current_email(event)):
        return _err(403, "FORBIDDEN", f"{what} 권한이 없습니다 (관리자 전용)")
    return None


def _load(customer_id: str, channel_id: str):
    item = notification_channel_table().get_item(
        Key={"customer_id": storage_key(customer_id), "channel_id": channel_id}).get("Item")
    return channel_from_item(item) if item else None


def _unavailable_reason(adapter) -> str:
    """이 유형이 **이 배포에서** 보낼 수 없는 이유. 빈 문자열이면 쓸 수 있다.

    이메일은 `ALERT_EMAIL_SENDER`(스택 파라미터)가 있어야 한다. 없는데 채널을 받으면 저장은 되고
    발송만 매번 실패한다 — 그 실패는 이력의 `delivery_results`에만 남아 설정 화면은 모른다(review-phase2 L3).
    """
    missing = adapter.missing_env(os.environ)
    if not missing:
        return ""
    return (f"서버 설정 {', '.join(missing)}이(가) 비어 있어 이 유형은 지금 발송할 수 없습니다 "
            f"(스택 파라미터로 설정 후 사용)")


def _query(customer_id: str) -> list[dict]:
    table = notification_channel_table()
    items: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": Key("customer_id").eq(storage_key(customer_id))}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


# ────────────────────────────────── 유형 카탈로그

def list_types(event: dict) -> dict:
    """채널 유형과 그 설정 필드. 설정 화면은 이걸로 폼을 그린다 —
    새 어댑터를 추가하면 화면도 자동으로 따라온다(design-notification-channels.md)."""
    return _ok({
        "types": [{
            "type": a.type,
            "label": a.label,
            "rate_limit_per_sec": a.rate_limit_per_sec,
            # 이 배포에서 실제로 보낼 수 있는가 — 화면은 못 쓰는 유형을 비활성으로 그린다
            "available": not _unavailable_reason(a),
            "unavailable_reason": _unavailable_reason(a),
            "fields": [{
                "name": f.name, "label": f.label,
                "required": f.required, "secret": f.secret, "max_len": f.max_len,
            } for f in a.fields],
        } for a in adapters.all_adapters()],
        "match_fields": list(MATCH_FIELDS),
        "severities": list(adapters.SEVERITY_ORDER),
    })


# ────────────────────────────────── CRUD

def list_channels(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    table = notification_channel_table()
    try:
        if "customer_id" in qs:
            # 명시 조회는 그 고객사 채널 + 전역 채널(그 고객사에도 적용되므로 같이 보여준다)
            customer_id = _customer_id(event)
            items = _query(customer_id)
            if customer_id:
                items += _query("")
        else:
            items = scan_all(table)
    except ClientError as e:
        logger.error("channel list failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널 목록을 읽지 못했습니다")

    channels = []
    for item in items:
        try:
            channels.append(channel_to_dict(channel_from_item(item)))
        except Exception as e:                                    # noqa: BLE001
            # 유형이 사라진(코드에서 제거된) 옛 행 — 목록 전체를 죽이지 않는다
            logger.warning("skipping unreadable channel %s: %s", item.get("channel_id"), e)
    channels.sort(key=lambda c: (c["is_global"], c["customer_id"], c["name"]))
    return _ok({"channels": channels, "total": len(channels)})


def create_channel(event: dict) -> dict:
    try:
        body = _body(event)
    except ChannelError as e:
        return _err(400, "VALIDATION_ERROR", str(e))
    customer_id = _customer_id(event, body)

    if not customer_id:
        denied = _forbidden(event, "전역 알림 채널 등록")
        if denied:
            return denied

    try:
        channel = validate_channel(body, customer_id=customer_id)
    except ChannelError as e:
        return _err(400, "VALIDATION_ERROR", str(e))
    reason = _unavailable_reason(channel.adapter)
    if reason:
        return _err(400, "TYPE_UNAVAILABLE", reason)

    try:
        existing = _query(customer_id)
        if len(existing) >= MAX_CHANNELS_PER_CUSTOMER:
            return _err(400, "LIMIT_EXCEEDED",
                        f"채널은 고객사당 최대 {MAX_CHANNELS_PER_CUSTOMER}개입니다")
        # 같은 ID가 있으면 덮지 않는다 — POST가 PUT 노릇을 하면 자격증명이 조용히 바뀐다(review-phase2 L2)
        notification_channel_table().put_item(
            Item=channel_to_item(channel, created_by=current_email(event)),
            ConditionExpression=Attr("channel_id").not_exists())
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return _err(409, "CONFLICT", "이미 있는 채널 ID입니다 — 수정은 PUT으로")
        logger.error("channel write failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 저장하지 못했습니다")

    return _ok(channel_to_dict(channel), status=201)


def update_channel(event: dict) -> dict:
    channel_id = (event.get("pathParameters") or {}).get("id", "")
    if not channel_id:
        return _err(400, "MISSING_PARAM", "채널 ID가 필요합니다")
    try:
        body = _body(event)
    except ChannelError as e:
        return _err(400, "VALIDATION_ERROR", str(e))
    customer_id = _customer_id(event, body)

    try:
        current = _load(customer_id, channel_id)
    except ClientError as e:
        logger.error("channel read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 읽지 못했습니다")
    if current is None:
        return _err(404, "NOT_FOUND", "채널을 찾을 수 없습니다")

    if not customer_id:
        denied = _forbidden(event, "전역 알림 채널 수정")
        if denied:
            return denied

    try:
        # 자격증명을 다시 안 보내도 유지된다 — 화면은 값을 모르고 가림 문자열만 갖고 있다.
        channel = validate_channel(
            {**body, "channel_id": channel_id}, customer_id=customer_id, existing=current)
    except ChannelError as e:
        return _err(400, "VALIDATION_ERROR", str(e))

    try:
        notification_channel_table().put_item(
            Item=channel_to_item(channel, created_by=current_email(event)))
    except ClientError as e:
        logger.error("channel update failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 저장하지 못했습니다")
    return _ok(channel_to_dict(channel))


def delete_channel(event: dict) -> dict:
    channel_id = (event.get("pathParameters") or {}).get("id", "")
    if not channel_id:
        return _err(400, "MISSING_PARAM", "채널 ID가 필요합니다")
    customer_id = _customer_id(event)

    try:
        current = _load(customer_id, channel_id)
    except ClientError as e:
        logger.error("channel read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 읽지 못했습니다")
    if current is None:
        return _err(404, "NOT_FOUND", "채널을 찾을 수 없습니다")

    if not customer_id:
        denied = _forbidden(event, "전역 알림 채널 삭제")
        if denied:
            return denied

    try:
        notification_channel_table().delete_item(
            Key={"customer_id": storage_key(customer_id), "channel_id": channel_id})
    except ClientError as e:
        logger.error("channel delete failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 삭제하지 못했습니다")
    return {"statusCode": 204, "body": ""}
