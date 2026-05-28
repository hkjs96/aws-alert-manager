"""
/resources endpoints.
"""

import functools
import json
import logging
import os
import re

import boto3
from botocore.exceptions import ClientError

from api_handler.cw_helper import (
    _parse_alarm_arn,
    extract_resource_from_alarm,
    list_alarms,
)
from api_handler.db import accounts_table, resource_inventory_table, scan_all
from common import dimension_builder
from common.tag_resolver import disk_path_to_tag_suffix
from common.resource_discovery import discover_resources, _get_session_for_account
from common.alarm_naming import _build_alarm_description, _pretty_alarm_name
from common.alarm_registry import (
    _DIMENSION_KEY_MAP,
    _GLOBAL_SERVICE_REGION,
    _METRIC_DISPLAY,
    _NAMESPACE_MAP,
    _metric_name_to_key,
)

logger = logging.getLogger(__name__)

_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")
_ALARM_NAME_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s+")
_ALARM_NAME_CONDITION_RE = re.compile(r"\s+(?:<=|>=|<|>)\s*[-+]?\d+(?:\.\d+)?\S*\s+\(TagName:\s*.+\)$")
_LIST_METRICS_PAGE_CAP = 20


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))


@functools.lru_cache(maxsize=None)
def _get_cw_client_for_region(region: str):
    return boto3.client("cloudwatch", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))


@functools.lru_cache(maxsize=None)
def _get_ec2_client_for_region(region: str):
    return boto3.client("ec2", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_rds_client_for_region(region: str):
    return boto3.client("rds", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_elbv2_client_for_region(region: str):
    return boto3.client("elbv2", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_lambda_client_for_region(region: str):
    return boto3.client("lambda", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_s3_client_for_region(region: str):
    return boto3.client("s3", region_name=region)


def _default_discovery_account() -> dict:
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "ap-northeast-2"
    )
    return {"account_id": "self", "regions": [region]}


def _resolve_target_accounts_for_sync(scope: dict) -> list[dict]:
    customer_id = scope.get("customer_id")
    account_id = scope.get("account_id")
    table_name = os.environ.get("ACCOUNTS_TABLE")
    if not table_name:
        return [_default_discovery_account()]

    from boto3.dynamodb.conditions import Key
    table = accounts_table()
    try:
        if customer_id and account_id:
            res = table.get_item(Key={"customer_id": customer_id, "account_id": account_id})
            return [res["Item"]] if res.get("Item") else []
        if customer_id:
            return table.query(KeyConditionExpression=Key("customer_id").eq(customer_id)).get("Items", [])
        if account_id:
            return table.query(IndexName="account_id-index", KeyConditionExpression=Key("account_id").eq(account_id)).get("Items", [])

        items = scan_all(table)
        if not items:
            return [_default_discovery_account()]
        return items
    except ClientError as e:
        logger.error("Failed to resolve target accounts for sync: %s", e)
        raise


def list_resources(event: dict) -> dict:
    return _list_inventory_resources(event)


def sync_resources(event: dict) -> dict:
    if not os.environ.get("RESOURCE_INVENTORY_TABLE") or not os.environ.get("ACCOUNTS_TABLE"):
        return _ok({
            "discovered": 0,
            "updated": 0,
            "removed": 0,
            "message": "Resource synchronization runs from the scheduled monitor",
        })

    scope = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
            scope = body.get("scope") or {}
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        accounts = _resolve_target_accounts_for_sync(scope)
        regions_override = scope.get("regions") or []
        for acc in accounts:
            if regions_override:
                acc["regions"] = regions_override
            else:
                acc["regions"] = list(acc.get("regions") or ["ap-northeast-2"])

        discovered = discover_resources(accounts)
        table = resource_inventory_table()
        for resource in discovered:
            resource_id = resource.get("resource_id") or resource.get("id")
            account_id = resource.get("account_id")
            if not resource_id or not account_id:
                continue

            existing = None
            try:
                resp = table.get_item(Key={"resource_id": resource_id, "account_id": account_id})
                existing = resp.get("Item")
            except ClientError as exc:
                logger.warning("Failed to read existing inventory snapshot for %s: %s", resource_id, exc)

            resource["entity_type"] = "resource"
            if existing:
                for field in ["alarm_count", "critical_count", "warning_count", "alarm_names", "alarm_state", "last_alarm_synced_at"]:
                    if field in existing:
                        resource[field] = existing[field]

            table.put_item(Item=resource)
        # Cleanup stale resource inventory items for the target accounts
        target_accounts = {acc["account_id"] for acc in accounts}
        discovered_keys = {(r["resource_id"], r["account_id"]) for r in discovered}
        removed_count = 0
        try:
            db_items = scan_all(table)
            for item in db_items:
                res_id = item.get("resource_id", "")
                acc_id = item.get("account_id", "")
                ent_type = item.get("entity_type", "resource")
                if ent_type == "resource" and acc_id in target_accounts:
                    if (res_id, acc_id) not in discovered_keys:
                        try:
                            table.delete_item(Key={"resource_id": res_id, "account_id": acc_id})
                            removed_count += 1
                        except ClientError as exc:
                            logger.error("Failed to delete stale resource %s: %s", res_id, exc)
        except ClientError as exc:
            logger.error("Failed to scan table for stale resource cleanup: %s", exc)

    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))

    count = len(discovered)
    return _ok({
        "discovered": count,
        "updated": count,
        "removed": removed_count,
        "message": f"{count} resources synchronized, {removed_count} stale resources removed",
    })


def get_resource(event: dict) -> dict:
    resource_id_or_name = _path_id(event)
    if not resource_id_or_name:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        resource = _find_resource_detail(resource_id_or_name)
    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))
    if not resource:
        return _err(404, "NOT_FOUND", f"Resource '{resource_id_or_name}' was not found")
    return _ok(resource)


def update_resource_monitoring(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "BAD_REQUEST", "JSON parse error")

    if "monitoring" not in body or not isinstance(body.get("monitoring"), bool):
        return _err(400, "VALIDATION_ERROR", "monitoring boolean is required")

    try:
        resource = _find_inventory_resource(resource_id)
        if not resource:
            return _err(404, "NOT_FOUND", f"Resource '{resource_id}' was not found")

        supported_types = ("EC2", "RDS", "AuroraRDS", "ALB", "Lambda", "S3")
        res_type = resource.get("type")
        if res_type not in supported_types:
            return _err(400, "UNSUPPORTED_RESOURCE_TYPE", f"Only {', '.join(supported_types)} monitoring toggle is supported")

        monitoring = bool(body["monitoring"])
        _set_resource_monitoring_tag(resource, monitoring)
        _update_inventory_monitoring(resource, monitoring)
    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))
    except (ValueError, RuntimeError) as exc:
        return _err(500, "INVENTORY_ERROR", str(exc))

    return _ok({
        "resource_id": resource_id,
        "monitoring": monitoring,
        "status": "updated",
    })


def get_resource_alarms(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        db_items = scan_all(resource_inventory_table())
    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))

    resource_alarms = [
        item for item in db_items
        if item.get("entity_type") == "alarm" and item.get("resource") == resource_id
    ]

    configs = []
    for alarm in resource_alarms:
        tags = alarm.get("tags") or {}
        threshold_val = alarm.get("threshold")
        if threshold_val is not None:
            try:
                threshold_val = float(threshold_val)
            except ValueError:
                pass
        configs.append({
            "alarm_name": alarm.get("alarm_name", ""),
            "metric_name": alarm.get("metric", ""),
            "namespace": alarm.get("namespace", ""),
            "mount_path": alarm.get("mount_path"),
            "threshold": threshold_val,
            "comparison": alarm.get("comparison", ""),
            "state": alarm.get("state", ""),
            "severity": alarm.get("severity", "SEV-5"),
            "monitoring": True,
            "period": alarm.get("period"),
            "evaluation_periods": alarm.get("evaluation_periods"),
            "datapoints_to_alarm": alarm.get("datapoints_to_alarm"),
            "treat_missing_data": alarm.get("treat_missing_data", "notBreaching"),
            "statistic": alarm.get("statistic", "Average"),
        })
    return _ok(configs)


def get_resource_metrics(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        db_items = scan_all(resource_inventory_table())
    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))

    resource = next(
        (item for item in db_items if _is_resource_snapshot(item) and _resource_id(item) == resource_id),
        None,
    )
    if not resource:
        alarm = next(
            (item for item in db_items if item.get("entity_type") == "alarm" and item.get("resource") == resource_id),
            None,
        )
        if alarm:
            resource_type = alarm.get("type")
        else:
            return _err(404, "NOT_FOUND", f"Resource '{resource_id}' was not found")
    else:
        resource_type = resource.get("type")

    namespaces = _NAMESPACE_MAP.get(resource_type, [])
    dim_key = _DIMENSION_KEY_MAP.get(resource_type, "")
    if not namespaces or not dim_key:
        return _ok([])

    dim_value = _dimension_value(resource_type, resource_id)
    region = _GLOBAL_SERVICE_REGION.get(resource_type)
    cw = _get_cw_client_for_region(region) if region else _get_cw_client()

    seen = set()
    items = []
    for namespace in namespaces:
        try:
            metrics = _paginated_list_metrics(cw, namespace, dim_key, dim_value)
        except ClientError as exc:
            logger.error("list_metrics failed (%s/%s): %s", namespace, dim_value, exc)
            continue
        for metric in metrics:
            metric_name = metric.get("MetricName", "")
            key = (namespace, metric_name)
            if key in seen:
                continue
            seen.add(key)
            items.append(_metric_catalog_entry(namespace, metric_name, resource_type))

    items.sort(key=lambda item: (item["namespace"], item["metric_name"]))
    return _ok(items)


def get_disk_paths(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        resp = _get_cw_client().list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
        )
    except ClientError as exc:
        return _err(500, "CW_ERROR", str(exc))

    paths = []
    seen = set()
    for metric in resp.get("Metrics", []):
        path = next((dim["Value"] for dim in metric.get("Dimensions", []) if dim["Name"] == "path"), None)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return _ok(sorted(paths))


def create_resource_alarm(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_BODY", "Invalid JSON body")

    metric_name = body.get("metric_name", "")
    threshold = body.get("threshold")
    mount_path = body.get("mount_path")
    severity = body.get("severity", "SEV-5")
    if not metric_name or threshold is None:
        return _err(400, "MISSING_PARAM", "metric_name and threshold are required")
    if metric_name == "disk_used_percent" and not mount_path:
        return _err(400, "MISSING_PARAM", "mount_path is required for disk_used_percent")

    try:
        existing_alarms = list_alarms()
    except ClientError as exc:
        return _err(500, "CW_ERROR", str(exc))

    resource_alarms = _alarms_for_resource(existing_alarms, resource_id)
    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"Resource '{resource_id}' was not found")
    resource_type = _get_resource_type(resource_alarms[0]["AlarmName"])

    region = _GLOBAL_SERVICE_REGION.get(resource_type)
    cw = _get_cw_client_for_region(region) if region else _get_cw_client()
    resource_name = _get_instance_name(resource_id) if resource_type == "EC2" else ""

    if metric_name == "disk_used_percent":
        namespace = "CWAgent"
        dims = _get_disk_dimensions_for_path(resource_id, mount_path, cw)
        if not dims:
            return _err(404, "NO_METRIC", f"No metric found for path '{mount_path}'")
        metric_key = f"disk_used_percent_{mount_path.lstrip('/') or 'root'}"
    else:
        resolved = dimension_builder._resolve_metric_dimensions(
            resource_id, metric_name, resource_type, cw=cw
        )
        if not resolved:
            return _err(404, "NO_METRIC", f"Metric '{metric_name}' was not found")
        namespace, dims = resolved
        metric_key = _metric_name_to_key(metric_name) or metric_name

    alarm_name = _pretty_alarm_name(resource_type, resource_id, resource_name, metric_key, float(threshold))
    description = _build_alarm_description(resource_type, resource_id, metric_key)
    sns_arn = os.environ.get("SNS_TOPIC_ARN_ALERT", "")

    try:
        cw.put_metric_alarm(
            AlarmName=alarm_name,
            AlarmDescription=description,
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dims,
            Statistic="Average",
            Period=300,
            EvaluationPeriods=1,
            Threshold=float(threshold),
            ComparisonOperator="GreaterThanThreshold",
            ActionsEnabled=True,
            AlarmActions=[sns_arn] if sns_arn else [],
            OKActions=[sns_arn] if sns_arn else [],
            TreatMissingData="notBreaching",
            Tags=[{"Key": "Severity", "Value": severity}],
        )
    except ClientError as exc:
        return _err(500, "CW_ERROR", str(exc))

    return _ok({"alarm_name": alarm_name, "metric_name": metric_name, "mount_path": mount_path}, status=201)


def update_resource_alarms(event: dict) -> dict:
    resource_id = _path_id(event)
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id is required")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_BODY", "Invalid JSON body")

    configs = body.get("configs")
    if not isinstance(configs, list):
        return _err(400, "INVALID_BODY", "configs must be a list")

    try:
        resource_alarms = _alarms_for_resource(list_alarms(), resource_id)
    except ClientError as exc:
        return _err(500, "CW_ERROR", str(exc))

    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"Resource '{resource_id}' was not found")

    results = []
    updated = 0
    for config in configs:
        if not isinstance(config, dict):
            return _err(400, "INVALID_BODY", "each config must be an object")
        alarm = _find_alarm_for_config(resource_alarms, config)
        if not alarm:
            metric_key = config.get("metric_key") or config.get("metric_name") or ""
            return _err(404, "NOT_FOUND", f"Alarm for metric '{metric_key}' was not found")

        try:
            alarm_name = _update_metric_alarm(alarm, config)
            _sync_threshold_tag_for_alarm(resource_id, alarm, config)
        except (TypeError, ValueError) as exc:
            return _err(400, "INVALID_BODY", str(exc))
        except ClientError as exc:
            return _err(500, "CW_ERROR", str(exc))

        updated += 1
        results.append({"alarm_name": alarm_name, "status": "updated"})

    return _ok({
        "job_id": "alarm-config-save",
        "status": "completed",
        "total_count": len(configs),
        "completed_count": updated,
        "failed_count": 0,
        "results": results,
    })


def _list_inventory_resources(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    resource_type = qs.get("resource_type") or None
    search = (qs.get("search") or "").lower()
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)

    try:
        persisted = scan_all(resource_inventory_table())
    except ClientError as exc:
        return _err(500, "AWS_ERROR", str(exc))

    items_by_id = {}
    for resource in _resource_snapshots(persisted):
        resource_id = resource.get("resource_id") or resource.get("id")
        if not resource_id:
            continue
        status = resource.get("status", "active")
        source = resource.get("inventory_source", "aws")

        items_by_id[resource_id] = _inventory_item(
            {**resource, "resource_id": resource_id, "status": status},
            source,
            _alarm_info_from_resource(resource),
            True
        )

    items = list(items_by_id.values())
    if resource_type:
        items = [item for item in items if item.get("type") == resource_type]
    if search:
        items = [
            item for item in items
            if search in item.get("id", "").lower() or search in item.get("name", "").lower()
        ]

    total = len(items)
    start = (page - 1) * page_size
    return _ok({"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size})


def _inventory_item(resource: dict, source: str, alarm_info: dict, persisted: bool) -> dict:
    account_id = resource.get("account_id", "")
    return {
        "id": resource.get("resource_id") or resource.get("id", ""),
        "name": resource.get("name") or resource.get("resource_id") or resource.get("id", ""),
        "type": resource.get("type", ""),
        "region": resource.get("region", ""),
        "account": account_id,
        "account_id": account_id,
        "customer_id": resource.get("customer_id", ""),
        "monitoring": bool(resource.get("monitoring", False)),
        "status": resource.get("status", "active"),
        "inventory_source": source,
        "persisted": persisted,
        "alarm_count": alarm_info.get("count", 0),
        "alarms": _alarm_summary(alarm_info),
    }


def _alarm_summary(alarm_info: dict) -> dict:
    return {
        "critical": alarm_info.get("critical", 0),
        "warning": alarm_info.get("warning", 0),
        "count": alarm_info.get("count", 0),
    }


def _resource_snapshots(items: list[dict]) -> list[dict]:
    return [item for item in items if _is_resource_snapshot(item)]


def _alarm_snapshots(items: list[dict]) -> list[dict]:
    return [item for item in items if _is_alarm_snapshot(item)]


def _resource_id(item: dict) -> str:
    return item.get("resource_id") or item.get("id", "")


def _is_resource_snapshot(item: dict) -> bool:
    entity_type = item.get("entity_type")
    if entity_type == "resource":
        return True
    if entity_type:
        return False
    return not _resource_id(item).startswith("alarm#")


def _is_alarm_snapshot(item: dict) -> bool:
    entity_type = item.get("entity_type")
    if entity_type == "alarm":
        return True
    if entity_type:
        return False
    return _resource_id(item).startswith("alarm#")


def _alarm_info_from_resource(resource: dict) -> dict:
    return {
        "count": int(resource.get("alarm_count") or 0),
        "critical": int(resource.get("critical_count") or 0),
        "warning": int(resource.get("warning_count") or 0),
    }


def _path_id(event: dict) -> str:
    return (event.get("pathParameters") or {}).get("id", "")


def _find_resource_detail(resource_id_or_name: str) -> dict | None:
    persisted = scan_all(resource_inventory_table())

    for resource in _resource_snapshots(persisted):
        resource_id = resource.get("resource_id") or resource.get("id")
        if not resource_id:
            continue
        if resource_id == resource_id_or_name or resource.get("name") == resource_id_or_name:
            status = resource.get("status", "active")
            source = resource.get("inventory_source", "aws")
            return _inventory_item(
                {**resource, "resource_id": resource_id, "status": status},
                source,
                _alarm_info_from_resource(resource),
                True,
            )
    return None


def _find_inventory_resource(resource_id: str) -> dict | None:
    if not os.environ.get("RESOURCE_INVENTORY_TABLE"):
        return None
    for resource in scan_all(resource_inventory_table()):
        if (resource.get("resource_id") or resource.get("id")) == resource_id:
            return resource
    return None


def _find_account(account_id: str) -> dict | None:
    from boto3.dynamodb.conditions import Key
    table = accounts_table()
    try:
        resp = table.query(
            IndexName="account_id-index",
            KeyConditionExpression=Key("account_id").eq(account_id)
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except ClientError as exc:
        logger.warning("Failed to query accounts_table for account_id %s: %s", account_id, exc)
        return None


def _set_resource_monitoring_tag(resource: dict, monitoring: bool) -> None:
    resource_id = resource.get("resource_id") or resource.get("id")
    resource_type = resource.get("type")
    region = resource.get("region") or os.environ.get("AWS_REGION") or "ap-northeast-2"
    account_id = resource.get("account_id")

    if not resource_id or not resource_type or not account_id:
        raise ValueError("Missing required resource attributes (id, type, account_id)")

    account_meta = _find_account(account_id) if account_id else None
    role_arn = account_meta.get("role_arn") if account_meta else ""

    use_assume_role = False
    if role_arn:
        try:
            current_account = boto3.client("sts").get_caller_identity().get("Account", "")
            if account_id != current_account:
                use_assume_role = True
        except ClientError:
            pass

    if use_assume_role and account_meta:
        session = _get_session_for_account(account_meta, region)
        if not session:
            raise RuntimeError(f"Failed to obtain AWS Session for account {account_id} in {region}")
        ec2_client = session.client("ec2")
        rds_client = session.client("rds")
        elbv2_client = session.client("elbv2")
        lambda_client = session.client("lambda")
        s3_client = session.client("s3")
    else:
        ec2_client = _get_ec2_client_for_region(region)
        rds_client = _get_rds_client_for_region(region)
        elbv2_client = _get_elbv2_client_for_region(region)
        lambda_client = _get_lambda_client_for_region(region)
        s3_client = _get_s3_client_for_region(region)

    value = "on" if monitoring else "off"

    if resource_type == "EC2":
        ec2_client.create_tags(
            Resources=[resource_id],
            Tags=[{"Key": "Monitoring", "Value": value}],
        )
    elif resource_type in ("RDS", "AuroraRDS"):
        arn = f"arn:aws:rds:{region}:{account_id}:db:{resource_id}"
        rds_client.add_tags_to_resource(
            ResourceName=arn,
            Tags=[{"Key": "Monitoring", "Value": value}],
        )
    elif resource_type == "ALB":
        elbv2_client.add_tags(
            ResourceArns=[resource_id],
            Tags=[{"Key": "Monitoring", "Value": value}],
        )
    elif resource_type == "Lambda":
        arn = resource.get("arn")
        if not arn:
            arn = f"arn:aws:lambda:{region}:{account_id}:function:{resource_id}"
        lambda_client.tag_resource(
            Resource=arn,
            Tags={"Monitoring": value},
        )
    elif resource_type == "S3":
        tags = []
        try:
            resp = s3_client.get_bucket_tagging(Bucket=resource_id)
            tags = resp.get("TagSet", [])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchTagSet":
                raise

        updated_tags = [t for t in tags if t["Key"] != "Monitoring"]
        updated_tags.append({"Key": "Monitoring", "Value": value})

        s3_client.put_bucket_tagging(
            Bucket=resource_id,
            Tagging={"TagSet": updated_tags}
        )
    else:
        raise ValueError(f"Unsupported resource type: {resource_type}")


def _update_inventory_monitoring(resource: dict, monitoring: bool) -> None:
    if not os.environ.get("RESOURCE_INVENTORY_TABLE"):
        return
    resource_id = resource.get("resource_id") or resource.get("id")
    account_id = resource.get("account_id")
    if not resource_id or not account_id:
        raise ValueError("Inventory item is missing resource_id or account_id")
    resource_inventory_table().update_item(
        Key={"resource_id": resource_id, "account_id": account_id},
        UpdateExpression="SET monitoring = :monitoring",
        ExpressionAttributeValues={":monitoring": monitoring},
    )


def _get_tag_name(alarm_name: str) -> str:
    match = _ALARM_NAME_RE.match(alarm_name)
    return match.group(2) if match else ""


def _get_resource_type(alarm_name: str) -> str:
    parsed = extract_resource_from_alarm(alarm_name)
    if parsed:
        return parsed[0]
    match = _ALARM_NAME_RE.match(alarm_name)
    return match.group(1) if match else ""


def _alarms_for_resource(alarms: list[dict], resource_id: str) -> list[dict]:
    return [alarm for alarm in alarms if _get_tag_name(alarm.get("AlarmName", "")) == resource_id]


def _find_alarm_for_config(alarms: list[dict], config: dict) -> dict | None:
    metric_key = config.get("metric_key") or config.get("metric_name")
    if not metric_key:
        return None
    metric_name = _metric_key_to_name(metric_key)
    mount_path = config.get("mount_path") or _mount_path_from_metric_key(metric_key)
    for alarm in alarms:
        if alarm.get("MetricName") != metric_name:
            continue
        if mount_path and _alarm_mount_path(alarm) != mount_path:
            continue
        return alarm
    for alarm in alarms:
        if metric_key in alarm.get("AlarmName", ""):
            return alarm
    return None


def _metric_key_to_name(metric_key: str) -> str:
    if ":" in metric_key:
        metric_key = metric_key.split(":", 1)[0]
    for name in (metric_key, metric_key.split("_/", 1)[0]):
        if _metric_name_to_key(name) == metric_key:
            return name
    return metric_key


def _mount_path_from_metric_key(metric_key: str) -> str:
    if ":" not in metric_key:
        return ""
    return metric_key.split(":", 1)[1]


def _alarm_mount_path(alarm: dict) -> str | None:
    if alarm.get("MetricName") != "disk_used_percent":
        return None
    return next(
        (dim["Value"] for dim in alarm.get("Dimensions", []) if dim.get("Name") == "path"),
        None,
    )


def _update_metric_alarm(alarm: dict, config: dict) -> str:
    if "threshold" not in config or config.get("threshold") is None:
        raise ValueError("threshold is required")

    region, _ = _parse_alarm_arn(alarm.get("AlarmArn", ""))
    cw = _get_cw_client_for_region(region) if region != "unknown" else _get_cw_client()
    kwargs = _metric_alarm_update_kwargs(alarm, config)
    previous_name = alarm["AlarmName"]
    next_name = kwargs["AlarmName"]
    cw.put_metric_alarm(**kwargs)

    severity = config.get("severity")
    alarm_arn = _alarm_arn_for_name(alarm, next_name)
    if severity and alarm_arn:
        try:
            cw.tag_resource(ResourceARN=alarm_arn, Tags=[{"Key": "Severity", "Value": str(severity)}])
        except ClientError as exc:
            logger.warning("Failed to update alarm severity tag for %s: %s", next_name, exc)
    if next_name != previous_name:
        cw.delete_alarms(AlarmNames=[previous_name])
    return next_name


def _sync_threshold_tag_for_alarm(resource_id: str, alarm: dict, config: dict) -> None:
    if _get_resource_type(alarm.get("AlarmName", "")) != "EC2":
        return
    tag_key = _threshold_tag_key(alarm, config)
    if not tag_key:
        return
    tag_value = _threshold_tag_value(config)
    if tag_value is None:
        return
    region, _ = _parse_alarm_arn(alarm.get("AlarmArn", ""))
    ec2 = _get_ec2_client_for_region(region) if region != "unknown" else _get_ec2_client()
    ec2.create_tags(
        Resources=[resource_id],
        Tags=[{"Key": tag_key, "Value": tag_value}],
    )


def _threshold_tag_key(alarm: dict, config: dict) -> str:
    metric_name = alarm.get("MetricName", "")
    if metric_name == "disk_used_percent":
        mount_path = config.get("mount_path") or _alarm_mount_path(alarm)
        if not mount_path:
            return ""
        return f"Threshold_Disk_{disk_path_to_tag_suffix(mount_path)}"
    aliases = {
        "CPUUtilization": "CPU",
        "mem_used_percent": "Memory",
    }
    tag_metric = aliases.get(metric_name) or config.get("metric_key") or metric_name
    if not tag_metric or ":" in str(tag_metric):
        return ""
    return f"Threshold_{tag_metric}"


def _threshold_tag_value(config: dict) -> str | None:
    if config.get("monitoring") is False:
        return "off"
    if "threshold" not in config or config.get("threshold") is None:
        return None
    threshold = float(config["threshold"])
    if threshold <= 0:
        return None
    return str(int(threshold)) if threshold == int(threshold) else f"{threshold:g}"


def _metric_alarm_update_kwargs(alarm: dict, config: dict) -> dict:
    threshold = float(config["threshold"])
    alarm_name = _updated_alarm_name(alarm, config, threshold)
    kwargs = {
        "AlarmName": alarm_name,
        "MetricName": alarm["MetricName"],
        "Namespace": alarm["Namespace"],
        "Dimensions": alarm.get("Dimensions", []),
        "Period": alarm.get("Period", 300),
        "EvaluationPeriods": alarm.get("EvaluationPeriods", 1),
        "Threshold": threshold,
        "ComparisonOperator": _comparison_operator(config.get("direction"), alarm),
        "ActionsEnabled": bool(config.get("monitoring", alarm.get("ActionsEnabled", True))),
        "OKActions": alarm.get("OKActions", []),
        "AlarmActions": alarm.get("AlarmActions", []),
        "InsufficientDataActions": alarm.get("InsufficientDataActions", []),
        "TreatMissingData": alarm.get("TreatMissingData", "notBreaching"),
        "Tags": _alarm_tags(alarm, config),
    }
    optional_fields = (
        "AlarmDescription",
        "DatapointsToAlarm",
        "EvaluateLowSampleCountPercentile",
        "ExtendedStatistic",
        "Statistic",
        "Unit",
    )
    for field in optional_fields:
        value = alarm.get(field)
        if value is not None:
            kwargs[field] = value
    if "Unit" not in kwargs and config.get("unit"):
        kwargs["Unit"] = config["unit"]
    if "Statistic" not in kwargs and "ExtendedStatistic" not in kwargs:
        kwargs["Statistic"] = "Average"
    return kwargs


def _updated_alarm_name(alarm: dict, config: dict, threshold: float) -> str:
    resource_id = _get_tag_name(alarm.get("AlarmName", ""))
    resource_type = _get_resource_type(alarm.get("AlarmName", ""))
    metric_key = _alarm_metric_key(alarm, config)
    if not resource_id or not resource_type or not metric_key:
        return alarm["AlarmName"]
    resource_name = _alarm_resource_name(alarm, metric_key)
    return _pretty_alarm_name(resource_type, resource_id, resource_name, metric_key, threshold)


def _alarm_metric_key(alarm: dict, config: dict) -> str:
    if alarm.get("MetricName") == "disk_used_percent":
        path = config.get("mount_path") or _alarm_mount_path(alarm) or _mount_path_from_metric_key(
            config.get("metric_key", "")
        )
        suffix = path.lstrip("/") or "root"
        return f"disk_used_percent_{suffix}"
    return _metric_key_to_name(config.get("metric_key") or alarm.get("MetricName", ""))


def _alarm_resource_name(alarm: dict, metric_key: str) -> str:
    name = alarm.get("AlarmName", "")
    body = _ALARM_NAME_PREFIX_RE.sub("", name, count=1)
    body = _ALARM_NAME_CONDITION_RE.sub("", body)
    metric_display = _alarm_metric_display(metric_key)
    suffix = f" {metric_display}"
    if body.endswith(suffix):
        return body[:-len(suffix)]
    if " " in body:
        return body.rsplit(" ", 1)[0]
    return ""


def _alarm_metric_display(metric_key: str) -> str:
    if metric_key.startswith("disk_used_percent_"):
        suffix = metric_key[len("disk_used_percent_"):]
        return "disk_used_percent(/)" if suffix == "root" else f"disk_used_percent(/{suffix})"
    return _metric_key_to_name(metric_key)


def _alarm_tags(alarm: dict, config: dict) -> list[dict]:
    tags = {tag["Key"]: tag["Value"] for tag in alarm.get("Tags", [])}
    if config.get("severity"):
        tags["Severity"] = str(config["severity"])
    tags.setdefault("ManagedBy", "AlarmManager")
    return [{"Key": key, "Value": value} for key, value in tags.items()]


def _alarm_arn_for_name(alarm: dict, alarm_name: str) -> str | None:
    alarm_arn = alarm.get("AlarmArn")
    if not alarm_arn:
        return None
    return alarm_arn.rsplit(":", 1)[0] + f":{alarm_name}"


def _comparison_operator(direction: str | None, alarm: dict) -> str:
    if not direction:
        return alarm.get("ComparisonOperator", "GreaterThanThreshold")
    return {
        ">": "GreaterThanThreshold",
        ">=": "GreaterThanOrEqualToThreshold",
        "<": "LessThanThreshold",
        "<=": "LessThanOrEqualToThreshold",
    }.get(direction, alarm.get("ComparisonOperator", "GreaterThanThreshold"))


def _dimension_value(resource_type: str, resource_id: str) -> str:
    if resource_type in ("ALB", "NLB", "TG"):
        return dimension_builder._extract_elb_dimension(resource_id)
    return resource_id


def _paginated_list_metrics(cw, namespace: str, dim_key: str, dim_value: str) -> list[dict]:
    metrics = []
    next_token = None
    for _ in range(_LIST_METRICS_PAGE_CAP):
        kwargs = {"Namespace": namespace, "Dimensions": [{"Name": dim_key, "Value": dim_value}]}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = cw.list_metrics(**kwargs)
        metrics.extend(resp.get("Metrics", []))
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return metrics


def _metric_catalog_entry(namespace: str, metric_name: str, resource_type: str) -> dict:
    metric_key = _metric_name_to_key(metric_name) or metric_name
    display = _METRIC_DISPLAY.get(metric_key, {})
    if isinstance(display, tuple):
        _, direction, unit = display
    else:
        direction = display.get("direction", ">")
        unit = display.get("unit")
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "unit": unit,
        "direction": direction or ">",
        "needs_mount_path": metric_name == "disk_used_percent",
        "resource_type": resource_type,
    }


def _get_instance_name(instance_id: str) -> str:
    try:
        resp = _get_ec2_client().describe_instances(InstanceIds=[instance_id])
        tags = resp["Reservations"][0]["Instances"][0].get("Tags", [])
        return next((tag["Value"] for tag in tags if tag["Key"] == "Name"), "")
    except (ClientError, IndexError, KeyError):
        return ""


def _get_disk_dimensions_for_path(instance_id: str, mount_path: str, cw) -> list[dict]:
    try:
        resp = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        )
    except ClientError:
        return []

    allowed = {"InstanceId", "device", "fstype", "path"}
    for metric in resp.get("Metrics", []):
        dims = metric.get("Dimensions", [])
        path = next((dim["Value"] for dim in dims if dim["Name"] == "path"), None)
        if path == mount_path:
            return [dim for dim in dims if dim["Name"] in allowed]
    return []


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
