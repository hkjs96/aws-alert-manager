"""
Daily Monitor Orchestrator — 멀티 어카운트 Fan-out

MONITORED_ACCOUNTS 환경변수(JSON)에서 계정 목록을 읽어
각 계정마다 Worker Lambda(daily_monitor)를 비동기로 invoke한다.
Worker들은 병렬로 실행되므로 전체 소요 시간 = 가장 느린 계정 1개 처리 시간.

Phase 1: 계정 목록을 MONITORED_ACCOUNTS 환경변수(JSON)에서 로드
Phase 2: DynamoDB Accounts 테이블 조회로 교체 예정

환경변수:
  MONITORED_ACCOUNTS (JSON array, 필수):
    [
      {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/AlarmManagerRole"},
      {"account_id": "self", "role_arn": ""}   # role_arn 빈 문자열 = 현재 계정(AssumeRole 생략)
    ]
  WORKER_FUNCTION_NAME (str, 필수): Worker Lambda 함수 이름
"""

import functools
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_lambda_client():
    return boto3.client("lambda")


def lambda_handler(event, context):
    accounts = _load_accounts()
    if not accounts:
        logger.warning("No accounts to process. Check MONITORED_ACCOUNTS env var.")
        return {"status": "no_accounts", "dispatched": 0}

    worker_fn = os.environ["WORKER_FUNCTION_NAME"]
    lambda_client = _get_lambda_client()

    dispatched, failed = [], []
    for account in accounts:
        account_id = account.get("account_id", "unknown")
        try:
            lambda_client.invoke(
                FunctionName=worker_fn,
                InvocationType="Event",  # 비동기 — Worker 완료를 기다리지 않음
                Payload=json.dumps(account).encode(),
            )
            dispatched.append(account_id)
            logger.info("Dispatched worker for account: %s", account_id)
        except ClientError as e:
            logger.error("Failed to invoke worker for account %s: %s", account_id, e)
            failed.append(account_id)

    logger.info(
        "Orchestrator done: dispatched=%d, failed=%d", len(dispatched), len(failed)
    )
    return {
        "status": "dispatched",
        "dispatched": len(dispatched),
        "failed": len(failed),
        "accounts": dispatched,
    }


def _load_accounts() -> list[dict]:
    """계정 목록 로드. Phase 2: DynamoDB 조회로 교체."""
    raw = os.environ.get("MONITORED_ACCOUNTS", "")
    if not raw:
        # 미설정 시 현재 계정 단일 모드로 폴백 (기존 동작 유지)
        logger.info("MONITORED_ACCOUNTS not set — single-account fallback")
        return [{"account_id": "self", "role_arn": ""}]

    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("MONITORED_ACCOUNTS JSON parse error: %s", e)
        return []

    if not isinstance(accounts, list):
        logger.error("MONITORED_ACCOUNTS must be a JSON array, got: %s", type(accounts))
        return []

    return accounts
