"""
/alert/incidents (requirements R4, tasks 2.1.3~2.1.4)

GET  /alert/incidents           → 인시던트 목록 + MTTA/MTTR 집계
GET  /alert/incidents/{id}      → 하나 (타임라인 포함)
POST /alert/incidents/{id}/ack  → 확인 처리 — 확인자·시각을 남기고 에스컬레이션을 멈춘다

**확인은 한 번만 기록된다.** 두 번째 확인이 시각을 덮으면 MTTA가 거짓이 되고, "누가 먼저
잡았나"라는 기록의 목적도 사라진다. 이미 확인된 건은 200으로 현재 상태를 돌려준다 —
사람이 버튼을 두 번 눌렀다고 오류를 보일 이유는 없다.
"""

import json
import logging
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from api_handler.db import incident_table, scan_all
from api_handler.identity import current_email
from common.incident import (
    STATUS_RESOLVED,
    acknowledge,
    from_item,
    summarize,
    to_dict,
)
from common.incident_store import MAX_ATTEMPTS, IncidentConflict, load, save

logger = logging.getLogger(__name__)

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str, ensure_ascii=False)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status,
            "body": json.dumps({"code": code, "message": message}, ensure_ascii=False)}


def _load(incident_id: str) -> dict | None:
    item = incident_table().get_item(Key={"incident_id": incident_id}).get("Item")
    return from_item(item) if item else None


def list_incidents(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    customer_id = str(qs.get("customer_id", "") or "").strip()
    status = str(qs.get("status", "") or "").strip()
    try:
        limit = max(1, min(MAX_LIMIT, int(qs.get("limit", DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    table = incident_table()
    try:
        if customer_id:
            items, kwargs = [], {
                "IndexName": "customer_id-index",
                "KeyConditionExpression": Key("customer_id").eq(customer_id),
                "ScanIndexForward": False,
            }
            while True:
                resp = table.query(**kwargs)
                items.extend(resp.get("Items", []))
                last = resp.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
        else:
            items = scan_all(table)
    except ClientError as e:
        logger.error("incident list failed: %s", e)
        return _err(503, "STORAGE_ERROR", "인시던트를 읽지 못했습니다")

    incidents = [to_dict(from_item(i)) for i in items]
    if status:
        incidents = [i for i in incidents if i.get("status") == status]
    # 집계는 필터 적용 후·건수 제한 전 값이다 — 화면 요약이 보이는 것만 세면 거짓이 된다.
    stats = summarize(incidents)
    incidents.sort(key=lambda i: str(i.get("triggered_at", "")), reverse=True)
    truncated = len(incidents) > limit
    return _ok({"incidents": incidents[:limit], "summary": stats,
                "truncated": truncated, "limit": limit})


def get_incident(event: dict) -> dict:
    incident_id = (event.get("pathParameters") or {}).get("id", "")
    if not incident_id:
        return _err(400, "MISSING_PARAM", "인시던트 ID가 필요합니다")
    try:
        incident = _load(incident_id)
    except ClientError as e:
        logger.error("incident read failed: %s", e)
        return _err(503, "STORAGE_ERROR", "인시던트를 읽지 못했습니다")
    if incident is None:
        return _err(404, "NOT_FOUND", "인시던트를 찾을 수 없습니다")
    return _ok(to_dict(incident))


def ack_incident(event: dict) -> dict:
    """확인 처리 (R4-3). 확인자는 로그인 신원에서 온다 — 본문으로 받으면 남을 대신 확인할 수 있다.

    저장은 읽은 버전일 때만 들어간다(review-phase2 H2). 폭풍 중에 사람이 확인 버튼을 누르는 바로
    그 순간 라우터가 새 발화를 합치고 있다 — 통째로 덮어쓰면 확인이 사라지거나 방금 합친 구성원이
    사라진다. 충돌하면 다시 읽어 그 위에 확인을 얹는다.
    """
    incident_id = (event.get("pathParameters") or {}).get("id", "")
    if not incident_id:
        return _err(400, "MISSING_PARAM", "인시던트 ID가 필요합니다")

    who = current_email(event)
    if not who:
        return _err(403, "FORBIDDEN", "확인자를 알 수 없습니다")

    table = incident_table()
    for _ in range(MAX_ATTEMPTS):
        try:
            incident, version = load(table, incident_id)
        except ClientError as e:
            logger.error("incident read failed: %s", e)
            return _err(503, "STORAGE_ERROR", "인시던트를 읽지 못했습니다")
        if incident is None:
            return _err(404, "NOT_FOUND", "인시던트를 찾을 수 없습니다")
        if incident.get("status") == STATUS_RESOLVED:
            return _err(409, "ALREADY_RESOLVED", "이미 해소된 인시던트입니다")

        now = datetime.now(timezone.utc)
        updated = acknowledge(incident, by=who, now=now)
        if updated.get("acknowledged_at") == incident.get("acknowledged_at"):
            # 이미 확인됨 — 첫 확인자를 그대로 두고 현재 상태를 돌려준다
            return _ok(to_dict(incident))

        try:
            saved = save(table, updated, now=now, expected_version=version)
        except IncidentConflict:
            logger.info("incident %s changed while acknowledging — re-applying", incident_id)
            continue
        except ClientError as e:
            logger.error("incident ack write failed: %s", e)
            return _err(503, "STORAGE_ERROR", "확인 처리를 저장하지 못했습니다")
        return _ok(to_dict(saved))

    return _err(409, "CONFLICT", "다른 갱신과 계속 겹칩니다 — 잠시 후 다시 시도하세요")
