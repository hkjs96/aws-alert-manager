"""
/bulk 엔드포인트

POST /bulk/monitoring  → 다수 리소스 모니터링 일괄 전환

태그가 진실이다(docs/specs/monitoring-tag-contract D3). 그래서 이 경로도 리소스별 `PUT /resources/{id}/monitoring`과 **같은
순서**로 간다: ① 인벤토리에서 리소스 확인 → ② 리소스에 Monitoring 태그 쓰기(RGT) → ③ 인벤토리 monitoring 플래그 → ④ 알람
생성/삭제는 SQS 워커(`create_alarms`/`delete_alarms`)에 비동기로. ①~③은 API 핸들러가 동기로 한다 — 리소스 하나가 실패해도
나머지는 계속, 실패는 job의 failed_count에 바로 적히고 응답의 `failed`로 돌아간다.

2026-09-16까지는 태그·인벤토리를 건너뛰고 워커가 알람만 만들었다(`toggle_monitoring`) — 다음 daily run이 태그 기준으로
되돌려 "켰는데 하루 뒤 꺼지는" 경로였다. 프런트의 Enable/Disable 모달은 그래서 리소스별 PUT을 쓴다(`lib/bulk-toggle.ts`);
이 엔드포인트는 큰 선택을 비동기로 처리해야 할 때를 위해 같은 의미로 고쳤다.
"""

import functools
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from api_handler.db import job_status_table, resource_inventory_table, scan_all
from api_handler.routes.resources import (
    _find_account,
    _set_resource_monitoring_tag,
    _update_inventory_monitoring,
)
from common import SUPPORTED_RESOURCE_TYPES

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_sqs():
    return boto3.client("sqs")


def _queue_url() -> str:
    return os.environ["BULK_OPERATION_QUEUE_URL"]


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message}, ensure_ascii=False)}


def _inventory_by_id(resource_ids: set[str]) -> dict[str, dict]:
    """요청한 ID들의 인벤토리 항목 — 테이블을 한 번만 훑는다(리소스별 `_find_inventory_resource`는 ID마다 스캔한다)."""
    if not os.environ.get("RESOURCE_INVENTORY_TABLE"):
        return {}
    found: dict[str, dict] = {}
    for item in scan_all(resource_inventory_table()):
        if item.get("entity_type") == "alarm":
            continue
        rid = item.get("resource_id") or item.get("id")
        if rid in resource_ids:
            found[rid] = item
    return found


def _record_failures(job_id: str, failed: int, finished: bool) -> None:
    """태그/인벤토리 단계에서 떨어진 리소스는 워커를 거치지 않으므로 여기서 failed_count에 적는다."""
    now = datetime.now(timezone.utc).isoformat()
    expr = "ADD failed_count :n SET updated_at = :now"
    values: dict = {":n": failed, ":now": now}
    names: dict = {}
    if finished:
        expr += ", #st = :st, finished_at = :now"
        names["#st"] = "status"
        values[":st"] = "failed"
    kwargs = {"Key": {"job_id": job_id}, "UpdateExpression": expr, "ExpressionAttributeValues": values}
    if names:
        kwargs["ExpressionAttributeNames"] = names
    try:
        job_status_table().update_item(**kwargs)
    except ClientError as e:
        logger.error("job_status failed_count 갱신 실패 (job_id=%s): %s", job_id, e)


def bulk_monitoring(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "BAD_REQUEST", "JSON 파싱 오류")

    resource_ids: list[str] = body.get("resource_ids") or []
    resource_type: str = body.get("resource_type") or ""
    monitoring: bool = bool(body.get("monitoring", True))

    if not resource_ids or not resource_type:
        return _err(400, "BAD_REQUEST", "resource_ids, resource_type 필수")
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        return _err(400, "UNSUPPORTED_RESOURCE_TYPE", f"Unsupported resource type: {resource_type}")

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    total = len(resource_ids)
    now = datetime.now(timezone.utc).isoformat()

    try:
        job_status_table().put_item(Item={
            "job_id": job_id,
            "status": "pending",
            "total_count": total,
            "completed_count": 0,
            "failed_count": 0,
            "created_at": now,
        })
    except ClientError as e:
        return _err(500, "INTERNAL_ERROR", str(e))

    inventory = _inventory_by_id(set(resource_ids))
    sqs = _get_sqs()
    queue_url = _queue_url()
    failed_ids: list[str] = []
    queued = 0
    enqueue_errors = 0

    for resource_id in resource_ids:
        resource = inventory.get(resource_id)
        if not resource or resource.get("type") != resource_type:
            logger.warning("bulk monitoring: %s is not in the inventory as %s — skipped", resource_id, resource_type)
            failed_ids.append(resource_id)
            continue

        # ②③ 태그가 진실 — 알람보다 먼저 쓴다. 실패하면 알람도 만들지 않는다(daily run이 되돌릴 알람은 만들지 않는다).
        try:
            _set_resource_monitoring_tag(resource, monitoring)
            _update_inventory_monitoring(resource, monitoring)
        except (ClientError, ValueError, RuntimeError) as e:
            logger.error("bulk monitoring: tag/inventory update failed for %s (%s): %s", resource_id, resource_type, e)
            failed_ids.append(resource_id)
            continue

        account_id = resource.get("account_id")
        account = _find_account(account_id) if account_id else None
        msg = {
            "job_id": job_id,
            "action": "create_alarms" if monitoring else "delete_alarms",
            "resource_id": resource_id,
            "resource_type": resource_type,
            # 즉시 생성에 필요한 디멘션 힌트(_lb_arn·_api_type…)는 인벤토리에 영속화돼 있다 — 리소스별 PUT과 같은 태그 셋.
            "resource_tags": {"Monitoring": "on", **(resource.get("dim_hints") or {})} if monitoring else {},
            "role_arn": (account or {}).get("role_arn") or "",
        }
        try:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(msg),
                MessageGroupId=job_id,
                MessageDeduplicationId=f"{job_id}-{resource_id}",
            )
        except ClientError as e:
            logger.error("SQS 전송 실패 resource=%s: %s", resource_id, e)
            failed_ids.append(resource_id)
            enqueue_errors += 1
            continue
        queued += 1

    if enqueue_errors and enqueue_errors == total:
        return _err(500, "QUEUE_ERROR", "SQS 전송 전체 실패")

    if failed_ids:
        _record_failures(job_id, len(failed_ids), finished=(queued == 0))

    return {
        "statusCode": 202,
        "body": json.dumps({
            "job_id": job_id,
            "total": total,
            "status": "pending" if queued else "failed",
            "queued": queued,
            "failed": failed_ids,
        }),
    }
