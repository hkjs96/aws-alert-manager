"""CloudWatch query helpers for alarms, resources, and dashboard stats."""

import functools
import logging
import re

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# [EC2] label metric >threshold (TagName: resource_id)
_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")


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
    except Exception as e:
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
    kwargs: dict = {
        "AlarmTypes": ["MetricAlarm"],
        "AlarmNamePrefix": alarm_name_prefix,
    }
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
        result = extract_resource_from_alarm(alarm["AlarmName"])
        if not result:
            continue
        rtype, tag_name = result
        
        if tag_name not in overlay:
            overlay[tag_name] = {
                "critical": 0,
                "warning": 0,
                "count": 0,
                "alarms": []
            }
        
        overlay[tag_name]["count"] += 1
        overlay[tag_name]["alarms"].append(alarm["AlarmName"])
        
        if alarm.get("StateValue") == "ALARM":
            tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
            sev = tags.get("Severity", "SEV-5")
            if sev in ("SEV-1", "SEV-2"):
                overlay[tag_name]["critical"] += 1
            else:
                overlay[tag_name]["warning"] += 1
                
    return overlay


def count_registered_accounts(customer_id: str | None = None, account_id: str | None = None) -> int:
    accounts = _load_registered_accounts(customer_id=customer_id, account_id=account_id)
    return len(accounts) if accounts else 1


def _parse_alarm_arn(alarm_arn: str) -> tuple[str, str]:
    """Extract (region, account_id) from AlarmArn. Return ("unknown", "unknown") on parse failure."""
    parts = alarm_arn.split(":")
    region = parts[3] if len(parts) > 3 and parts[3] else "unknown"
    account_id = parts[4] if len(parts) > 4 and parts[4] else "unknown"
    return region, account_id


def extract_resource_from_alarm(alarm_name: str) -> tuple[str, str] | None:
    """Extract (resource_type, tag_name) from an alarm name."""
    m = _ALARM_NAME_RE.match(alarm_name)
    if m:
        return m.group(1), m.group(2)
    return None


def get_dashboard_stats(customer_id: str | None = None, account_id: str | None = None) -> dict:
    """Aggregate dashboard stats from registered accounts."""
    try:
        all_alarms = list_alarms(customer_id=customer_id, account_id=account_id)
    except ClientError:
        return {"monitored_count": 0, "active_alarms": 0, "unmonitored_count": 0, "account_count": 0}

    resources: set[tuple[str, str]] = set()
    active_alarms = 0
    for alarm in all_alarms:
        result = extract_resource_from_alarm(alarm["AlarmName"])
        if result:
            resources.add(result)
        if alarm.get("StateValue") == "ALARM":
            active_alarms += 1

    return {
        "monitored_count": len(resources),
        "active_alarms": active_alarms,
        "unmonitored_count": 0,
        "account_count": count_registered_accounts(customer_id=customer_id, account_id=account_id),
    }


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
        result = extract_resource_from_alarm(alarm["AlarmName"])
        if not result:
            continue
        rtype, tag_name = result
        key = (rtype, tag_name)
        if key not in resource_map:
            region, account_id = _parse_alarm_arn(alarm.get("AlarmArn", ""))
            resource_map[key] = {
                "id": tag_name,
                "name": tag_name,
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
