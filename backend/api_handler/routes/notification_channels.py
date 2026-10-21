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

from api_handler.authz import scope_for
from api_handler.db import notification_channel_table, scan_all
from api_handler.identity import admin_enforced, current_email, is_admin
from common import notification_adapters as adapters
from common.notification_channel import (
    MATCH_FIELDS,
    MAX_CHANNELS_PER_CUSTOMER,
    Channel,
    ChannelError,
    channel_from_item,
    channel_to_dict,
    channel_to_item,
    storage_key,
    matches,
    validate_channel,
    validate_match,
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


def _not_found() -> dict:
    return _err(404, "NOT_FOUND", "채널을 찾을 수 없습니다")


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
    # 전역 채널은 모두에게 보인다(설정 변경은 관리자 전용). 고객사 채널은 범위 안 것만.
    scope = scope_for(event)
    channels = [c for c in channels if c["is_global"] or scope.allows_customer(c["customer_id"])]
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
    elif not scope_for(event).allows_customer(customer_id):
        return _err(404, "NOT_FOUND", "고객사를 찾을 수 없습니다")

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
    if customer_id and not scope_for(event).allows_customer(customer_id):
        return _not_found()

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
    if customer_id and not scope_for(event).allows_customer(customer_id):
        return _not_found()

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


# ────────────────────────────────── 저장 전 미리보기

PREVIEW_DAYS = 30


def _history_rows(customer_id: str, days: list[str]) -> list[dict]:
    """고객사의 날짜별 이력(customer_day-index). 보낼 이벤트(final_action=notify)만."""
    from api_handler.db import event_history_table
    table, rows = event_history_table(), []
    for day in days:
        kwargs = {"IndexName": "customer_day-index",
                  "KeyConditionExpression": Key("customer_day").eq(f"{customer_id}#{day}"),
                  "FilterExpression": Attr("final_action").eq("notify")}
        while True:
            resp = table.query(**kwargs)
            rows.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return rows


def preview_channel(event: dict) -> dict:
    """이 조건으로 저장하면 얼마나 받게 되는가 — 지난 30일 실제 이력에 조건을 대 본다.

    발송은 묶음(그룹) 단위라 메시지 수 ≈ 조건에 맞는 이벤트의 서로 다른 group_id 수다. 그룹 대표만 판정하는
    라우터와 달리 구성원 하나라도 맞으면 세므로 약간 많게 나온다(상한 추정).
    """
    from datetime import datetime, timedelta, timezone
    from api_handler.db import customers_table

    try:
        body = _body(event)
        match = validate_match(body.get("match") or {})
    except ChannelError as e:
        return _err(400, "VALIDATION_ERROR", str(e))
    customer_id = _customer_id(event, body)
    scope = scope_for(event)
    if not customer_id:
        denied = _forbidden(event, "전역 알림 채널 미리보기")
        if denied:
            return denied
    elif not scope.allows_customer(customer_id):
        return _err(404, "NOT_FOUND", "고객사를 찾을 수 없습니다")

    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(PREVIEW_DAYS)]
    probe = Channel(channel_id="preview", customer_id=customer_id, name="preview", type="webhook",
                    config={}, match=match, enabled=True)
    try:
        customers = [customer_id] if customer_id else [c["customer_id"] for c in scan_all(customers_table())]
        rows = [r for cid in customers for r in _history_rows(cid, days)]
    except (ClientError, KeyError) as e:
        logger.error("channel preview failed: %s", e)
        return _err(503, "STORAGE_ERROR", "이력을 읽지 못했습니다")

    hit = [r for r in rows if matches(probe, r)]
    messages = len({r.get("group_id") or r.get("event_id") for r in hit})
    by_severity: dict[str, int] = {}
    for r in hit:
        sev = str(r.get("severity") or "-")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return _ok({
        "days": PREVIEW_DAYS,
        "messages": messages,
        "per_day": round(messages / PREVIEW_DAYS, 1),
        "events": len(hit),
        "events_total": len(rows),
        "by_severity": dict(sorted(by_severity.items())),
    })


def test_channel(event: dict) -> dict:
    """저장된 채널로 테스트 메시지 한 건 — 웹훅·주소가 맞는지 바로 확인한다. 인시던트·이력은 만들지 않는다.

    결과(성공/HTTP 상태/오류)를 그대로 돌려준다. 오류 문자열은 발송기가 자격증명을 가린 것이다(_safe_error).
    """
    from datetime import datetime, timezone
    from common.notification_adapters import Notification
    from common.notification_send import deliver

    channel_id = (event.get("pathParameters") or {}).get("id", "")
    if not channel_id:
        return _err(400, "MISSING_PARAM", "채널 ID가 필요합니다")
    customer_id = _customer_id(event)
    if not customer_id:
        denied = _forbidden(event, "전역 알림 채널 테스트")
        if denied:
            return denied
    elif not scope_for(event).allows_customer(customer_id):
        return _not_found()
    try:
        channel = _load(customer_id, channel_id)
    except ClientError as e:
        logger.error("channel read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "채널을 읽지 못했습니다")
    if channel is None:
        return _not_found()
    reason = _unavailable_reason(channel.adapter)
    if reason:
        return _err(400, "TYPE_UNAVAILABLE", reason)

    console = os.environ.get("ALERT_CONSOLE_URL", "")
    note = Notification(
        title="[테스트] 알림 채널 연결 확인",
        severity="SEV-5",
        customer_id=customer_id,
        state="OK",
        reason=f"{current_email(event) or '관리자'}님이 설정 화면에서 보낸 테스트 메시지입니다. 실제 알람이 아닙니다.",
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        url=f"{console.rstrip('/')}/settings" if console else "",
    )
    result = deliver(channel, note, sender=os.environ.get("ALERT_EMAIL_SENDER", ""))
    logger.info("channel test %s/%s by %s: ok=%s status=%s", customer_id or "-", channel_id,
                current_email(event), result.ok, result.status)
    return _ok(result.to_dict())
