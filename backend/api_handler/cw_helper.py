"""CloudWatch query helpers for alarms, resources, and dashboard stats."""

import functools
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from common.alarm_builder import resolve_alarm_severity
from common.alarm_identity import identify_alarm, parse_alarm_name

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_cw():
    return boto3.client("cloudwatch")


@functools.lru_cache(maxsize=1)
def _get_current_account_id() -> str:
    return boto3.client("sts").get_caller_identity().get("Account", "")


def _load_registered_accounts(customer_id: str | None = None, account_id: str | None = None) -> list[dict]:
    """Read registered monitoring accounts. Return [] so callers can fall back to the current account."""
    try:
        from api_handler.db import accounts_table, query_by_pk, scan_all

        if customer_id:
            accounts = query_by_pk(accounts_table(), "customer_id", customer_id)
        else:
            accounts = scan_all(accounts_table())
    except (ClientError, KeyError) as e:
        logger.warning("Registered account lookup failed; using current account fallback: %s", e)
        return []

    if account_id:
        accounts = [a for a in accounts if a.get("account_id") == account_id]
    return accounts


def _get_cw_for_account(account: dict, region: str):
    role_arn = account.get("role_arn") or ""
    account_id = account.get("account_id") or ""
    if account_id and account_id == _get_current_account_id():
        return boto3.client("cloudwatch", region_name=region)
    if not role_arn:
        return boto3.client("cloudwatch", region_name=region)

    sts = boto3.client("sts")
    resp = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"ApiHandlerAlarmList-{account.get('account_id', 'unknown')}",
    )
    creds = resp["Credentials"]
    return boto3.client(
        "cloudwatch",
        region_name=region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _describe_alarms(cw, alarm_name_prefix: str, state_value: str | None) -> list[dict]:
    kwargs: dict = {"AlarmTypes": ["MetricAlarm"]}
    if alarm_name_prefix:   # 빈 접두어 = 이름 무관 전부(고객이 만든 알람 포함)
        kwargs["AlarmNamePrefix"] = alarm_name_prefix
    if state_value:
        kwargs["StateValue"] = state_value

    alarms = []
    paginator = cw.get_paginator("describe_alarms")
    for page in paginator.paginate(**kwargs):
        alarms.extend(page.get("MetricAlarms", []))
    return alarms


def list_alarms(
    alarm_name_prefix: str = "[",
    state_value: str | None = None,
    customer_id: str | None = None,
    account_id: str | None = None,
) -> list[dict]:
    """List CloudWatch alarms across registered accounts and regions."""
    accounts = _load_registered_accounts(customer_id=customer_id, account_id=account_id)
    if not accounts:
        try:
            return _describe_alarms(_get_cw(), alarm_name_prefix, state_value)
        except ClientError as e:
            logger.error("CloudWatch describe_alarms failed: %s", e)
            raise

    alarms: list[dict] = []
    errors: list[ClientError] = []
    attempted = 0
    for account in accounts:
        regions = account.get("regions") or ["ap-northeast-2"]
        for region in regions:
            attempted += 1
            try:
                cw = _get_cw_for_account(account, region)
                alarms.extend(_describe_alarms(cw, alarm_name_prefix, state_value))
            except ClientError as e:
                logger.error(
                    "CloudWatch describe_alarms failed (account=%s, region=%s): %s",
                    account.get("account_id", "unknown"),
                    region,
                    e,
                )
                errors.append(e)

    if not alarms and errors and len(errors) == attempted:
        raise errors[0]
    return alarms


def get_alarm_overlay(customer_id: str | None = None, account_id: str | None = None) -> dict[str, dict]:
    """
    Get alarm status overlay indexed by resource_id.
    Returns: { resource_id: { "critical": N, "warning": N, "count": N, "alarms": [...] } }
    """
    try:
        all_alarms = list_alarms(customer_id=customer_id, account_id=account_id)
    except ClientError:
        return {}

    overlay = {}
    for alarm in all_alarms:
        identity = identify_alarm(alarm)
        if identity is None:
            continue
        # Canonical (full) resource id keys the overlay so inventory ids join directly.
        rid = identity.resource_id

        if rid not in overlay:
            overlay[rid] = {
                "critical": 0,
                "warning": 0,
                "count": 0,
                "alarms": []
            }

        overlay[rid]["count"] += 1
        overlay[rid]["alarms"].append(alarm["AlarmName"])

        if alarm.get("StateValue") == "ALARM":
            sev = resolve_alarm_severity(alarm)
            if sev in ("SEV-1", "SEV-2"):
                overlay[rid]["critical"] += 1
            else:
                overlay[rid]["warning"] += 1

    return overlay


def count_registered_accounts(customer_id: str | None = None, account_id: str | None = None,
                              scope=None) -> int:
    accounts = _load_registered_accounts(customer_id=customer_id, account_id=account_id)
    if scope is not None and not scope.unrestricted:
        # 범위가 제한되면 "현재 계정" 폴백(1)을 쓰지 않는다 — 중앙 계정은 고객사 없는 데이터다.
        return len(scope.filter(accounts))
    return len(accounts) if accounts else 1


def _parse_alarm_arn(alarm_arn: str) -> tuple[str, str]:
    """Extract (region, account_id) from AlarmArn. Return ("unknown", "unknown") on parse failure."""
    parts = alarm_arn.split(":")
    region = parts[3] if len(parts) > 3 and parts[3] else "unknown"
    account_id = parts[4] if len(parts) > 4 and parts[4] else "unknown"
    return region, account_id


def extract_resource_from_alarm(alarm_name: str) -> tuple[str, str] | None:
    """Extract (resource_type, tag_name) from an alarm *name* only.

    Prefer common.alarm_identity.identify_alarm(alarm) when the full alarm dict is
    available — it reads the AlarmDescription metadata (full resource id) first.
    """
    return parse_alarm_name(alarm_name)


def get_dashboard_stats(customer_id: str | None = None, account_id: str | None = None,
                        scope=None) -> dict:
    """Aggregate dashboard stats from DynamoDB resource and alarm snapshots."""
    try:
        from api_handler.db import scan_all, resource_inventory_table
        db_items = scan_all(resource_inventory_table())
    except ClientError:
        return {"monitored_count": 0, "active_alarms": 0, "unmonitored_count": 0, "account_count": 0}

    if scope is not None:
        db_items = scope.filter(db_items)

    db_resources = [item for item in db_items if _is_resource_snapshot(item)]
    db_alarms = [item for item in db_items if _is_alarm_snapshot(item)]

    if customer_id:
        db_resources = [r for r in db_resources if r.get("customer_id") == customer_id]
        res_ids_for_customer = {r.get("resource_id") for r in db_resources}
        db_alarms = [a for a in db_alarms if a.get("resource") in res_ids_for_customer]

    if account_id:
        db_resources = [r for r in db_resources if r.get("account_id") == account_id]
        db_alarms = [a for a in db_alarms if a.get("account_id") == account_id]

    monitored_count = sum(1 for r in db_resources if r.get("monitoring", False))
    firing = count_firing_alarms(customer_id, account_id, scope)
    if firing is None:   # 실시간 조회 실패 — 인벤토리(우리 알람만) 기준으로라도 보여 준다
        ours = sum(1 for alarm in db_alarms if alarm.get("state") == "ALARM")
        firing = {"ours": ours, "customer": None}
    connection = count_account_connections(customer_id, account_id, scope)

    return {
        "monitored_count": monitored_count,
        "active_alarms": firing["ours"] + (firing["customer"] or 0),
        "active_alarms_ours": firing["ours"],
        "active_alarms_customer": firing["customer"],
        "accounts_connected": connection["connected"],
        "accounts_failed": connection["failed"],
        "unmonitored_count": max(len(db_resources) - monitored_count, 0),
        "account_count": count_registered_accounts(customer_id=customer_id, account_id=account_id, scope=scope),
    }


def _snapshot_resource_id(item: dict) -> str:
    return item.get("resource_id") or item.get("id", "")


def _scoped_accounts(customer_id, account_id, scope) -> list[dict]:
    accounts = _load_registered_accounts(customer_id=customer_id, account_id=account_id)
    if scope is not None and not scope.unrestricted:
        accounts = scope.filter(accounts)
    return accounts


def live_alarms(customer_id=None, account_id=None, scope=None) -> list[dict] | None:
    """범위 안 계정의 CloudWatch 알람 전부(상태 무관, 고객이 만든 알람 포함). 항목에 `_account_id`·`_region`을 붙인다.

    인벤토리에는 우리 알람만 있다 — 고객 알람을 보려면 CloudWatch를 직접 봐야 한다. 인벤토리에 고객 알람을 넣지 않는 건
    고아 정리가 인벤토리 알람 행을 보기 때문이다(고객 알람을 지울 길을 만들지 않는다). 조회가 전부 실패하면 None.
    """
    accounts = _scoped_accounts(customer_id, account_id, scope)
    if not accounts and scope is not None and not scope.unrestricted:
        return []
    targets = tuple(sorted({(a.get("account_id") or "", region)
                            for a in accounts for region in (a.get("regions") or ["ap-northeast-2"])}))
    cached = _LIVE_CACHE.get(targets)
    if cached and time.monotonic() - cached[0] < _LIVE_TTL_SEC:
        return cached[1]
    by_id = {a.get("account_id") or "": a for a in accounts}
    try:
        if targets:
            # 계정×리전마다 AssumeRole+DescribeAlarms — 차례로 하면 대시보드가 5초 걸린다(HOME 실측). 동시에 돈다.
            with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
                pages = list(pool.map(lambda t: _alarms_in(by_id[t[0]], t[1]), targets))
            alarms = [a for page in pages for a in page]
        else:   # 등록 계정 없음(단일 계정 모드) — 이 계정, 이 리전
            alarms = _alarms_in({}, boto3.session.Session().region_name or "us-east-1")
    except (ClientError, BotoCoreError) as e:   # 자격 증명·네트워크 실패도 화면 전체를 깨지 않게
        logger.error("Live alarm lookup failed: %s", e)
        return None
    _LIVE_CACHE[targets] = (time.monotonic(), alarms)
    return alarms


def count_firing_alarms(customer_id=None, account_id=None, scope=None) -> dict | None:
    """지금 ALARM 상태인 알람 수 — 우리 알람과 고객이 만든 알람을 나눈다.

    인벤토리만 세면 고객 알람이 울리고 있어도 "All clear"가 된다(HOME 실측 2026-10-20: 고객 알람 2개 ALARM, 카드 0).
    조회 실패면 None — 호출부가 인벤토리 기준으로 대신한다.
    """
    alarms = live_alarms(customer_id, account_id, scope)
    if alarms is None:
        return None
    firing = [a for a in alarms if a.get("StateValue") == "ALARM"]
    ours = sum(1 for a in firing if identify_alarm(a) is not None)
    return {"ours": ours, "customer": len(firing) - ours}


# 알람 상태는 분 단위로 바뀐다 — 화면을 열 때마다 계정 전부를 다시 묻지 않는다(웜 컨테이너 안에서만).
_LIVE_TTL_SEC = 60
_LIVE_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def _alarms_in(account: dict, region: str) -> list[dict]:
    """한 계정·리전의 알람 전부. 스레드마다 전용 세션(boto3 기본 세션은 스레드 안전하지 않다)."""
    session = boto3.session.Session()
    role_arn = account.get("role_arn") or ""
    if role_arn and account.get("account_id") != _get_current_account_id():
        creds = session.client("sts").assume_role(
            RoleArn=role_arn, RoleSessionName=f"ApiHandlerLive-{account.get('account_id', 'unknown')}",
        )["Credentials"]
        session = boto3.session.Session(
            aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    alarms = _describe_alarms(session.client("cloudwatch", region_name=region), "", None)
    return [{**a, "_account_id": account.get("account_id") or "", "_region": region} for a in alarms]


def count_account_connections(customer_id=None, account_id=None, scope=None) -> dict:
    """마지막 연결 테스트 결과 기준. 테스트 전(untested)은 실패로 세지 않는다."""
    accounts = _scoped_accounts(customer_id, account_id, scope)
    return {
        "connected": sum(1 for a in accounts if a.get("connection_status") == "connected"),
        "failed": sum(1 for a in accounts if a.get("connection_status") == "failed"),
    }


def _is_resource_snapshot(item: dict) -> bool:
    entity_type = item.get("entity_type")
    if entity_type == "resource":
        return True
    if entity_type:
        return False
    return not _snapshot_resource_id(item).startswith("alarm#")


def _is_alarm_snapshot(item: dict) -> bool:
    entity_type = item.get("entity_type")
    if entity_type == "alarm":
        return True
    if entity_type:
        return False
    return _snapshot_resource_id(item).startswith("alarm#")


def get_resources_from_alarms(
    page: int = 1,
    page_size: int = 25,
    resource_type: str | None = None,
    search: str | None = None,
) -> dict:
    """Build a monitored resource list by parsing alarm names."""
    try:
        all_alarms = list_alarms()
    except ClientError:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    resource_map: dict[tuple[str, str], dict] = {}
    for alarm in all_alarms:
        identity = identify_alarm(alarm)
        if identity is None:
            continue
        rtype = identity.resource_type
        key = (rtype, identity.resource_id)
        if key not in resource_map:
            region, account_id = _parse_alarm_arn(alarm.get("AlarmArn", ""))
            resource_map[key] = {
                "id": identity.resource_id,
                "name": identity.tag_name or identity.resource_id,
                "type": rtype,
                "account": account_id,
                "region": region,
                "monitoring": True,
                "alarms": {"critical": 0, "warning": 0},
            }
        if alarm.get("StateValue") == "ALARM":
            tags = alarm.get("Tags", {})
            sev = next((t["Value"] for t in tags if t["Key"] == "Severity"), "SEV-5")
            if sev in ("SEV-1", "SEV-2"):
                resource_map[key]["alarms"]["critical"] += 1
            else:
                resource_map[key]["alarms"]["warning"] += 1

    items = list(resource_map.values())

    if resource_type:
        items = [r for r in items if r["type"] == resource_type]
    if search:
        lower = search.lower()
        items = [r for r in items if lower in r["id"].lower() or lower in r["name"].lower()]

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start: start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
