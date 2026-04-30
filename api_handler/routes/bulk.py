"""
/bulk 엔드포인트

POST /bulk/monitoring  → 다수 리소스 모니터링 일괄 전환 (SQS 비동기)
"""

import functools
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

from api_handler.db import job_status_table


@functools.lru_cache(maxsize=None)
def _get_sqs():
    return boto3.client("sqs")


def _queue_url() -> str:
    return os.environ["BULK_OPERATION_QUEUE_URL"]


def bulk_monitoring(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"code": "BAD_REQUEST", "message": "JSON 파싱 오류"})}

    resource_ids: list[str] = body.get("resource_ids") or []
    resource_type: str = body.get("resource_type") or ""
    monitoring: bool = bool(body.get("monitoring", True))
    role_arn: str = body.get("role_arn") or ""

    if not resource_ids or not resource_type:
        return {
            "statusCode": 400,
            "body": json.dumps({"code": "BAD_REQUEST", "message": "resource_ids, resource_type 필수"}),
        }

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
        return {"statusCode": 500, "body": json.dumps({"code": "INTERNAL_ERROR", "message": str(e)})}

    sqs = _get_sqs()
    queue_url = _queue_url()
    failed_enqueue = 0

    for resource_id in resource_ids:
        msg = {
            "job_id": job_id,
            "action": "toggle_monitoring",
            "resource_id": resource_id,
            "resource_type": resource_type,
            "resource_tags": body.get("resource_tags", {}).get(resource_id, {}),
            "monitoring": monitoring,
            "role_arn": role_arn,
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
            failed_enqueue += 1

    if failed_enqueue == total:
        return {"statusCode": 500, "body": json.dumps({"code": "QUEUE_ERROR", "message": "SQS 전송 전체 실패"})}

    return {
        "statusCode": 202,
        "body": json.dumps({"job_id": job_id, "total": total, "status": "pending"}),
    }
