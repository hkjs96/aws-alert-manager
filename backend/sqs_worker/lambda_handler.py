"""
SQS Worker Lambda — 벌크 알람 작업 비동기 처리

SQS FIFO 큐에서 메시지를 수신하여 리소스별 알람 CRUD를 수행한다.
각 메시지는 단일 리소스에 대한 단일 작업을 나타낸다.

메시지 스키마:
  {
    "job_id":       "job-xxx",
    "action":       "create_alarms" | "delete_alarms" | "sync_alarms" | "toggle_monitoring",
    "resource_id":  "i-xxx",
    "resource_type": "EC2",
    "resource_tags": {...},
    "monitoring":   true | false,  # toggle_monitoring 전용
    "role_arn":     "arn:aws:iam::...:role/...",  # 크로스 어카운트 (선택)
  }
"""

import functools
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from common import alarm_manager

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)

_VALID_ACTIONS = frozenset(
    {"create_alarms", "delete_alarms", "sync_alarms", "toggle_monitoring"}
)


# ──────────────────────────────────────────────
# DynamoDB 헬퍼
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_ddb():
    return boto3.resource("dynamodb")


def _job_status_table():
    return _get_ddb().Table(os.environ["JOB_STATUS_TABLE"])


def _increment_job_counter(job_id: str, success: bool) -> None:
    field = "completed_count" if success else "failed_count"
    try:
        _job_status_table().update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                f"ADD {field} :one "
                "SET #st = if_not_exists(#st, :in_progress), updated_at = :now"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":one": 1,
                ":in_progress": "in_progress",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except ClientError as e:
        logger.error("job_status 업데이트 실패 (job_id=%s): %s", job_id, e)


def _finalize_job(job_id: str) -> None:
    """completed + failed 합계가 total_count에 도달하면 최종 상태 기록."""
    try:
        item = _job_status_table().get_item(Key={"job_id": job_id}).get("Item")
        if not item:
            return
        total = int(item.get("total_count", 0))
        done = int(item.get("completed_count", 0)) + int(item.get("failed_count", 0))
        if done < total:
            return
        failed = int(item.get("failed_count", 0))
        final_status = "failed" if failed == total else (
            "partial_failure" if failed > 0 else "completed"
        )
        _job_status_table().update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #st = :s, finished_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":s": final_status,
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except ClientError as e:
        logger.error("job 최종화 실패 (job_id=%s): %s", job_id, e)


# ──────────────────────────────────────────────
# 크로스 어카운트 CW 클라이언트
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_cw_for_role(role_arn: str):
    """AssumeRole을 통해 대상 어카운트의 CloudWatch 클라이언트를 반환."""
    sts = boto3.client("sts")
    creds = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="sqs-worker",
    )["Credentials"]
    return boto3.client(
        "cloudwatch",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


# ──────────────────────────────────────────────
# 액션 핸들러
# ──────────────────────────────────────────────

def _run_action(msg: dict) -> None:
    action = msg["action"]
    resource_id = msg["resource_id"]
    resource_type = msg["resource_type"]
    resource_tags = msg.get("resource_tags") or {}
    role_arn = msg.get("role_arn") or ""

    cw = _get_cw_for_role(role_arn) if role_arn else None
    kwargs = {"cw": cw} if cw is not None else {}

    if action == "create_alarms":
        alarm_manager.create_alarms_for_resource(
            resource_id, resource_type, resource_tags, **kwargs
        )
    elif action == "delete_alarms":
        alarm_manager.delete_alarms_for_resource(
            resource_id, resource_type, **kwargs
        )
    elif action == "sync_alarms":
        alarm_manager.sync_alarms_for_resource(
            resource_id, resource_type, resource_tags, **kwargs
        )
    elif action == "toggle_monitoring":
        monitoring_on = bool(msg.get("monitoring", False))
        if monitoring_on:
            alarm_manager.create_alarms_for_resource(
                resource_id, resource_type, resource_tags, **kwargs
            )
        else:
            alarm_manager.delete_alarms_for_resource(
                resource_id, resource_type, **kwargs
            )
    else:
        raise ValueError(f"알 수 없는 action: {action}")


# ──────────────────────────────────────────────
# Lambda 진입점
# ──────────────────────────────────────────────

def lambda_handler(event: dict, context) -> dict:
    records = event.get("Records", [])
    batch_item_failures = []

    for record in records:
        message_id = record.get("messageId", "unknown")
        try:
            msg = json.loads(record["body"])
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("메시지 파싱 실패 (messageId=%s): %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})
            continue

        job_id = msg.get("job_id", "")
        success = False
        try:
            if msg.get("action") not in _VALID_ACTIONS:
                raise ValueError(f"유효하지 않은 action: {msg.get('action')}")
            _run_action(msg)
            success = True
            logger.info(
                "작업 완료: job_id=%s action=%s resource=%s",
                job_id, msg.get("action"), msg.get("resource_id"),
            )
        except ClientError as e:
            logger.error(
                "AWS 오류: job_id=%s resource=%s: %s",
                job_id, msg.get("resource_id"), e,
            )
            batch_item_failures.append({"itemIdentifier": message_id})
        except Exception as e:  # noqa: BLE001 — 최상위 핸들러
            logger.error(
                "처리 실패: job_id=%s resource=%s: %s",
                job_id, msg.get("resource_id"), e,
            )
            batch_item_failures.append({"itemIdentifier": message_id})
        finally:
            if job_id:
                _increment_job_counter(job_id, success)
                _finalize_job(job_id)

    return {"batchItemFailures": batch_item_failures}
