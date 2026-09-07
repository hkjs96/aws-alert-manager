"""
/alert/policy · /alert/silences 엔드포인트 (tasks 1.4.4 / 1.4.6)

GET    /alert/policy            → 지금 적용 중인 정제 정책 (환경변수 기준 + DB 덮어쓰기)
PUT    /alert/policy            → 정책 저장. **관리자 전용**
GET    /alert/silences          → 정비창 목록 (기본: 만료되지 않은 것)
POST   /alert/silences          → 정비창 등록
DELETE /alert/silences/{id}     → 정비창 취소

**권한은 폭발 반경으로 나눈다.** 정책은 전역이고 잘못 넣으면 모든 알림이 사라질 수 있어
관리자만 바꾼다. 정비창은 운영자의 일상 작업이지만, 고객사를 지정하지 않은 **전역 정비창**은
모든 고객사의 알림을 덮으므로 역시 관리자만 만들 수 있다.
(`ADMIN_EMAILS` 미설정 환경에서는 기존 라우트와 동일하게 제한이 적용되지 않는다.)

변경은 최대 `CONFIG_CACHE_TTL_SEC`(60초) 뒤 인제스터에 반영된다.
"""

import json
import logging
from datetime import datetime, timezone

from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from api_handler.db import alert_policy_table
from api_handler.identity import admin_enforced, current_email, is_admin
from common.alert_config import (
    CONFIG_POLICY,
    CONFIG_SILENCE,
    POLICY_DEFAULT,
    ConfigError,
    new_silence_id,
    parse_dt,
    policy_from_item,
    policy_to_dict,
    policy_to_item,
    silence_to_dict,
    silence_to_item,
    validate_policy,
    validate_silence,
)
from common.alert_suppression import SuppressionPolicy

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
        raise ConfigError("요청 본문이 JSON 형식이 아닙니다") from None
    if not isinstance(parsed, dict):
        raise ConfigError("요청 본문이 객체가 아닙니다")
    return parsed


def _forbidden(event: dict, what: str) -> dict | None:
    if admin_enforced() and not is_admin(current_email(event)):
        return _err(403, "FORBIDDEN", f"{what} 권한이 없습니다 (관리자 전용)")
    return None


def _base_policy() -> SuppressionPolicy:
    """환경변수 기준 정책 — DB에 없는 필드는 이 값이 남는다."""
    return SuppressionPolicy.from_env()


def get_policy(event: dict) -> dict:
    try:
        item = alert_policy_table().get_item(
            Key={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT}).get("Item")
    except ClientError as e:
        logger.error("policy read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정책을 읽지 못했습니다")
    policy = policy_from_item(_base_policy(), item)
    return _ok({
        "policy": policy_to_dict(policy),
        "source": "db" if item else "env",
        "updated_at": str((item or {}).get("updated_at", "")),
        "updated_by": str((item or {}).get("updated_by", "")),
    })


def put_policy(event: dict) -> dict:
    denied = _forbidden(event, "정제 정책 변경")
    if denied:
        return denied
    try:
        body = _body(event)
        policy = validate_policy(body, _base_policy())
    except ConfigError as e:
        return _err(400, "VALIDATION_ERROR", str(e))
    item = policy_to_item(policy, updated_by=current_email(event))
    try:
        alert_policy_table().put_item(Item=item)
    except ClientError as e:
        logger.error("policy write failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정책을 저장하지 못했습니다")
    return _ok({"policy": policy_to_dict(policy), "updated_at": item["updated_at"]})


def list_silences(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    include_expired = str(qs.get("include_expired", "")).lower() in ("1", "true", "yes")
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": Key("config_type").eq(CONFIG_SILENCE)}
    try:
        while True:
            resp = alert_policy_table().query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except ClientError as e:
        logger.error("silence list failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정비창을 읽지 못했습니다")

    silences = [silence_to_dict(i, now=now) for i in items]
    if not include_expired:
        silences = [s for s in silences if not s["expired"]]
    silences.sort(key=lambda s: s["starts_at"], reverse=True)
    return _ok({"silences": silences, "active": sum(1 for s in silences if s["active"])})


def create_silence(event: dict) -> dict:
    now = datetime.now(timezone.utc)
    try:
        body = _body(event)
        silence = validate_silence(body, now=now)
    except ConfigError as e:
        return _err(400, "VALIDATION_ERROR", str(e))

    if not silence.customer_id:
        denied = _forbidden(event, "전역 정비창 등록")
        if denied:
            return denied

    item = silence_to_item(silence, config_id=new_silence_id(now),
                           created_by=current_email(event), created_at=now)
    try:
        alert_policy_table().put_item(Item=item)
    except ClientError as e:
        logger.error("silence write failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정비창을 저장하지 못했습니다")
    return _ok(silence_to_dict(item, now=now), status=201)


def delete_silence(event: dict) -> dict:
    silence_id = (event.get("pathParameters") or {}).get("id", "")
    if not silence_id:
        return _err(400, "MISSING_PARAM", "정비창 ID가 필요합니다")
    table = alert_policy_table()
    try:
        item = table.get_item(
            Key={"config_type": CONFIG_SILENCE, "config_id": silence_id}).get("Item")
    except ClientError as e:
        logger.error("silence read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정비창을 읽지 못했습니다")
    if not item:
        return _err(404, "NOT_FOUND", "정비창을 찾을 수 없습니다")
    if not str(item.get("customer_id", "") or ""):
        denied = _forbidden(event, "전역 정비창 취소")
        if denied:
            return denied
    try:
        table.delete_item(Key={"config_type": CONFIG_SILENCE, "config_id": silence_id})
    except ClientError as e:
        logger.error("silence delete failed: %s", e)
        return _err(503, "STORAGE_ERROR", "정비창을 삭제하지 못했습니다")
    ends = parse_dt(item.get("ends_at"))
    return _ok({"id": silence_id, "deleted": True,
                "was_active": bool(ends and datetime.now(timezone.utc) < ends)})
