"""
Daily Monitor Orchestrator — 멀티 어카운트 Fan-out

**앱에 등록된 계정이 정본이다.** 계정마다 Worker Lambda(daily_monitor)를 비동기로 invoke하고,
Worker들은 병렬로 돌므로 전체 소요 시간 = 가장 느린 계정 1개 처리 시간.

2026-09-23까지 이 모듈은 `MONITORED_ACCOUNTS` 환경변수만 봤고 템플릿이 그 값을 빈 문자열로 줬다.
그래서 **어떤 고객사 계정을 등록해도 항상 현재 계정 하나로 폴백**했고, 데일리 런이 그 계정을 건드리지
않았다(첫 실고객 온보딩에서 드러남 — 등록·버스 권한·연결 테스트는 전부 정상인데 아무 일도 안 일어났다).
알림 전달(EventBridge → 중앙 버스)은 이 경로와 무관하게 동작하므로 증상이 "알람 생성만 안 된다"였다.

계정 목록 우선순위:
  1. `MONITORED_ACCOUNTS` (JSON array) — 수동 오버라이드. 비상시·로컬 실험용.
  2. `ACCOUNTS_TABLE` — 앱에서 등록한 계정. 평소 경로.
  3. 단일 계정 폴백 — 표가 없거나(초기 배포) 읽지 못했을 때. 조용히 아무것도 안 하는 것보다 낫다.

환경변수:
  WORKER_FUNCTION_NAME (str, 필수): Worker Lambda 함수 이름
  ACCOUNTS_TABLE (str): 등록된 계정 표
  MONITORED_ACCOUNTS (JSON array, 선택):
    [
      {"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/AlarmManagerMonitoringRole"},
      {"account_id": "self", "role_arn": ""}   # role_arn 빈 문자열 = 현재 계정(AssumeRole 생략)
    ]
"""

import functools
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


#: 표가 없거나 읽지 못했을 때 — 최소한 우리 계정은 돈다.
_SELF_ONLY = [{"account_id": "self", "role_arn": ""}]


@functools.lru_cache(maxsize=None)
def _get_lambda_client():
    return boto3.client("lambda")


@functools.lru_cache(maxsize=None)
def _get_ddb():
    return boto3.resource("dynamodb")


@functools.lru_cache(maxsize=1)
def _current_account_id() -> str:
    """우리 계정 ID. 실패하면 빈 문자열 — 자기 계정 판별만 못 하고 팬아웃은 계속한다."""
    try:
        return str(boto3.client("sts").get_caller_identity().get("Account", ""))
    except ClientError as e:
        logger.error("get_caller_identity failed — cannot tell which row is our own account: %s", e)
        return ""


def lambda_handler(event, context):
    accounts = _load_accounts()
    if not accounts:
        logger.warning("No accounts to process. Check MONITORED_ACCOUNTS env var.")
        return {"status": "no_accounts", "dispatched": 0}

    worker_fn = os.environ["WORKER_FUNCTION_NAME"]
    lambda_client = _get_lambda_client()

    # 스케줄이 실행 모드를 지정할 수 있다 (예: 주간 metric_snapshot).
    # 미지정 시 기존 daily 흐름 그대로.
    mode = event.get("mode", "") if isinstance(event, dict) else ""

    dispatched, failed = [], []
    for account in accounts:
        account_id = account.get("account_id", "unknown")
        payload = {**account, "mode": mode} if mode else account
        try:
            lambda_client.invoke(
                FunctionName=worker_fn,
                InvocationType="Event",  # 비동기 — Worker 완료를 기다리지 않음
                Payload=json.dumps(payload).encode(),
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
    """워커에 넘길 계정 목록 — 등록된 계정 표가 정본, 환경변수는 수동 오버라이드(모듈 문서 참조)."""
    raw = os.environ.get("MONITORED_ACCOUNTS", "")
    if raw:
        return _accounts_from_env(raw)

    table_name = os.environ.get("ACCOUNTS_TABLE", "")
    if not table_name:
        logger.info("ACCOUNTS_TABLE not set — single-account fallback")
        return list(_SELF_ONLY)

    try:
        rows = _scan_accounts(table_name)
    except ClientError as e:
        # 표를 못 읽는다고 아무것도 안 돌리면 그날 모니터링이 통째로 조용히 사라진다.
        logger.error("Could not read %s — falling back to the current account only: %s", table_name, e)
        return list(_SELF_ONLY)

    accounts = _dispatch_targets(rows)
    if not accounts:
        logger.info("No accounts registered in %s — single-account fallback", table_name)
        return list(_SELF_ONLY)
    logger.info("Loaded %d registered account(s) from %s", len(accounts), table_name)
    return accounts


def _accounts_from_env(raw: str) -> list[dict]:
    """`MONITORED_ACCOUNTS` 수동 오버라이드. 형식이 틀리면 **빈 목록** — 잘못된 지정으로 엉뚱한 계정을 돌리지 않는다."""
    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("MONITORED_ACCOUNTS JSON parse error: %s", e)
        return []

    if not isinstance(accounts, list):
        logger.error("MONITORED_ACCOUNTS must be a JSON array, got: %s", type(accounts))
        return []

    return accounts


def _scan_accounts(table_name: str) -> list[dict]:
    """등록된 계정 행 전체. 계정 수는 수십 단위라 Scan으로 충분하다.

    페이지네이션 주의(AGENTS.md AP-15): bare MagicMock 테이블로 테스트하면 `LastEvaluatedKey`가 항상
    truthy라 루프가 끝나지 않는다 — 테스트는 `scan.return_value`를 종료 페이지로 준다.
    """
    table = _get_ddb().Table(table_name)
    kwargs: dict = {"ProjectionExpression": "account_id, role_arn"}
    rows: list[dict] = []
    while True:
        resp = table.scan(**kwargs)
        rows.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return rows
        kwargs["ExclusiveStartKey"] = last


def _dispatch_targets(rows: list[dict]) -> list[dict]:
    """계정 행 → 워커 페이로드. 계정당 한 건으로 접는다.

    같은 AWS 계정이 여러 고객사 행에 달릴 수 있다(계정 표의 키가 customer_id + account_id) — 접지 않으면
    워커가 같은 계정을 여러 번 돌아 알람 동기화와 메트릭 조회가 그만큼 중복된다.

    우리 계정 자신은 `role_arn`을 비워 보낸다. 표의 값은 앱이 읽기용으로 쓰는 것이라 워커가 그걸로
    AssumeRole 하면 실패한다 — 자기 계정은 위임이 필요 없다(워커는 role_arn이 비면 전환을 건너뛴다).
    """
    me = _current_account_id()
    seen: set[str] = set()
    targets: list[dict] = []
    for row in rows:
        account_id = str(row.get("account_id") or "").strip()
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        role_arn = "" if account_id == me else str(row.get("role_arn") or "").strip()
        targets.append({"account_id": account_id, "role_arn": role_arn})
    return targets
