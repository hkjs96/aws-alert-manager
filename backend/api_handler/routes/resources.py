"""
/resources endpoints.
"""

import base64
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
from api_handler.db import accounts_table, resource_inventory_table, scan_all, query_by_pk
from common import SUPPORTED_RESOURCE_TYPES, dimension_builder
from common.tag_resolver import disk_path_to_tag_suffix
from common.resource_discovery import _get_session_for_account
from common.alarm_manager import sync_alarms_for_resource, delete_alarms_for_resource
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


@functools.lru_cache(maxsize=None)
def _get_tagging_client_for_region(region: str):
    """Resource Groups Tagging API 클라이언트 싱글턴 (모니터링 토글 태깅용)."""
    return boto3.client("resourcegroupstaggingapi", region_name=region)


def list_resources(event: dict) -> dict:
    return _list_inventory_resources(event)


# NOTE: 동기 sync_resources는 제거됨 — POST /resources/sync는 sync.import_resources
# (비동기 job, daily_monitor의 _handle_resources_sync_job)가 처리한다.


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

        res_type = resource.get("type")
        if res_type not in SUPPORTED_RESOURCE_TYPES:
            return _err(400, "UNSUPPORTED_RESOURCE_TYPE", f"Unsupported resource type: {res_type}")

        monitoring = bool(body["monitoring"])
        _set_resource_monitoring_tag(resource, monitoring)
        _update_inventory_monitoring(resource, monitoring)
        # 갭 축소: 토글 즉시 알람 생성/삭제. 실패해도 토글 자체는 성공 처리하고
        # 다음 daily monitor가 self-heal 하도록 한다(태그/인벤토리는 이미 반영됨).
        # KeyError: TG 등 힌트 의존 타입은 collector 내부 태그(_lb_arn 등) 없이는
        # 디멘션을 만들 수 없어 KeyError가 난다 — 즉시 생성은 스킵하고 daily에 위임.
        try:
            _apply_alarms_for_toggle(resource, monitoring)
        except (ClientError, ValueError, RuntimeError, KeyError) as exc:
            logger.warning(
                "Immediate alarm sync failed for %s (%s); will self-heal on next daily run: %s",
                resource_id, res_type, exc,
            )
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
    # 글로벌 서비스(CloudFront/Route53)는 us-east-1 고정, 그 외에는 리소스의 실제
    # 리전 CW를 사용한다(다른 리전 리소스의 메트릭이 빈 배열로 누락되지 않도록).
    region = _GLOBAL_SERVICE_REGION.get(resource_type) or (resource.get("region") if resource else None)
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

    # EC2가 api_handler와 다른 리전이면 default 리전 CW에는 disk 메트릭이 없어
    # 빈 배열이 된다. 인벤토리에서 리소스 리전을 찾아 해당 리전 CW를 사용한다.
    region = _resource_region(resource_id)
    cw = _get_cw_client_for_region(region) if region else _get_cw_client()

    try:
        resp = cw.list_metrics(
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


_RESOURCE_TOKEN_PREFIX = "r."


def _decode_resource_token(raw: str) -> str:
    """URL 토큰(base64url)을 원본 resource_id로 복원한다.

    프론트엔드(`encodeResourceId`)는 ARN처럼 슬래시·콜론을 포함한 resource_id를
    URL/API path에 안전하게 싣기 위해 base64url로 인코딩해 `r.<payload>` 토큰으로
    전달한다. 가역 토큰이라 매핑 테이블 없이 복원되며, 레거시 raw id(EC2 `i-...`)나
    리소스 name은 접두사가 없어 그대로 통과한다(상세: 루트 AGENTS.md AP-6).
    """
    if not raw.startswith(_RESOURCE_TOKEN_PREFIX):
        return raw
    payload = raw[len(_RESOURCE_TOKEN_PREFIX):]
    pad = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return raw
    # round-trip 가드: 정상 토큰만 복원하고 우연히 접두사가 겹친 raw 값은 보존한다.
    reencoded = base64.urlsafe_b64encode(decoded.encode("utf-8")).decode("ascii").rstrip("=")
    if reencoded != payload:
        return raw
    return decoded


def _path_id(event: dict) -> str:
    raw = (event.get("pathParameters") or {}).get("id", "")
    return _decode_resource_token(raw)


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


def _resource_region(resource_id: str) -> str | None:
    """인벤토리에서 리소스의 리전을 조회한다.

    resource_id가 파티션 키이므로 풀스캔 대신 Query 단건으로 찾는다. 조회 실패 시
    None을 반환해 호출부가 기본 리전 CW로 폴백하도록 한다(disk-paths가 깨지지 않게).
    """
    if not os.environ.get("RESOURCE_INVENTORY_TABLE"):
        return None
    try:
        items = query_by_pk(resource_inventory_table(), "resource_id", resource_id)
    except ClientError as exc:
        logger.warning("Region lookup failed for %s: %s", resource_id, exc)
        return None
    snapshot = next((item for item in items if _is_resource_snapshot(item)), None)
    return snapshot.get("region") if snapshot else None


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


# resource_type → ARN 템플릿. {id}=resource_id, {region}/{account} 치환.
# resource_id가 이미 ARN(arn:로 시작)이면 그대로 사용한다(ALB/NLB/TG).
# ECS는 인벤토리에 저장된 serviceArn(클러스터 포함)을 사용하므로 템플릿이 없다.
_ARN_TEMPLATES: dict[str, str] = {
    "EC2": "arn:aws:ec2:{region}:{account}:instance/{id}",
    "RDS": "arn:aws:rds:{region}:{account}:db:{id}",
    "AuroraRDS": "arn:aws:rds:{region}:{account}:db:{id}",
    "DocDB": "arn:aws:rds:{region}:{account}:db:{id}",
    "ElastiCache": "arn:aws:elasticache:{region}:{account}:cluster:{id}",
    "NAT": "arn:aws:ec2:{region}:{account}:natgateway/{id}",
    "Lambda": "arn:aws:lambda:{region}:{account}:function:{id}",
    "S3": "arn:aws:s3:::{id}",
    "SQS": "arn:aws:sqs:{region}:{account}:{id}",
    "DynamoDB": "arn:aws:dynamodb:{region}:{account}:table/{id}",
    "EFS": "arn:aws:elasticfilesystem:{region}:{account}:file-system/{id}",
    "CLB": "arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/{id}",
    "OpenSearch": "arn:aws:es:{region}:{account}:domain/{id}",
    "Backup": "arn:aws:backup:{region}:{account}:backup-vault:{id}",
    "DX": "arn:aws:directconnect:{region}:{account}:dxcon/{id}",
    "SageMaker": "arn:aws:sagemaker:{region}:{account}:endpoint/{id}",
    "SNS": "arn:aws:sns:{region}:{account}:{id}",
    "VPN": "arn:aws:ec2:{region}:{account}:vpn-connection/{id}",
    "CloudFront": "arn:aws:cloudfront::{account}:distribution/{id}",
    "Route53": "arn:aws:route53:::healthcheck/{id}",
    # ACM: resource_id가 곧 ARN. APIGW/MQ/MSK/WAF: 저장된 arn 사용(템플릿 재구성 불가).
}


def _resource_arn_for_tagging(resource: dict) -> str:
    """모니터링 토글 태깅 대상 ARN을 해석한다.

    우선순위: 인벤토리에 저장된 arn → resource_id가 이미 ARN → 타입별 템플릿 구성.
    (기존 인벤토리 항목은 다음 daily run 전까지 arn이 없을 수 있어 템플릿 폴백이 필요.)
    빈 문자열이면 ARN을 만들 수 없는 타입이다.
    """
    arn = resource.get("arn")
    if arn:
        return arn
    rid = resource.get("resource_id") or resource.get("id") or ""
    if rid.startswith("arn:"):
        return rid
    template = _ARN_TEMPLATES.get(resource.get("type", ""))
    if not template:
        return ""
    region = resource.get("region") or os.environ.get("AWS_REGION") or "ap-northeast-2"
    account_id = resource.get("account_id") or ""
    return template.format(region=region, account=account_id, id=rid)


def _resource_aws_session(resource: dict):
    """리소스 작업용 (session|None, region, account_id)을 반환한다.

    크로스 계정이면 AssumeRole 세션, 동일 계정이면 session=None(로컬 리전 클라이언트 사용).
    태깅 클라이언트와 CloudWatch 클라이언트가 같은 계정/리전 컨텍스트를 공유하도록 한다.

    글로벌 서비스(CloudFront/Route53)는 RGT 태깅·CW 알람 모두 us-east-1에서만
    동작하므로 인벤토리 region 값과 무관하게 us-east-1로 강제한다.
    (sync_alarms_for_resource의 글로벌 오버라이드는 cw=None일 때만 작동하는데
    토글 경로는 cw를 명시적으로 넘기므로 여기서 보정해야 한다.)
    """
    region = (
        _GLOBAL_SERVICE_REGION.get(resource.get("type", ""))
        or resource.get("region")
        or os.environ.get("AWS_REGION")
        or "ap-northeast-2"
    )
    account_id = resource.get("account_id")
    account_meta = _find_account(account_id) if account_id else None
    role_arn = account_meta.get("role_arn") if account_meta else ""
    if role_arn and account_meta:
        try:
            current_account = boto3.client("sts").get_caller_identity().get("Account", "")
        except ClientError:
            current_account = ""
        if account_id and account_id != current_account:
            session = _get_session_for_account(account_meta, region)
            if not session:
                raise RuntimeError(f"Failed to obtain AWS Session for account {account_id} in {region}")
            return session, region, account_id
    return None, region, account_id


def _set_resource_monitoring_tag(resource: dict, monitoring: bool) -> None:
    """Resource Groups Tagging API로 Monitoring=on/off 태그를 설정한다.

    타입별 네이티브 태깅 API 대신 단일 tag_resources 경로를 사용한다(타입 무관).
    대상 ARN은 _resource_arn_for_tagging로 해석한다. RGT tag_resources는 기존 태그를
    보존하며 지정한 키만 갱신하므로 S3도 read-modify-write가 필요 없다.
    """
    resource_id = resource.get("resource_id") or resource.get("id")
    resource_type = resource.get("type")
    account_id = resource.get("account_id")

    if not resource_id or not resource_type or not account_id:
        raise ValueError("Missing required resource attributes (id, type, account_id)")

    arn = _resource_arn_for_tagging(resource)
    if not arn:
        raise ValueError(f"Cannot resolve tagging ARN for {resource_type} {resource_id}")

    session, region, _ = _resource_aws_session(resource)
    if session is not None:
        tagging_client = session.client("resourcegroupstaggingapi", region_name=region)
    else:
        tagging_client = _get_tagging_client_for_region(region)

    value = "on" if monitoring else "off"
    resp = tagging_client.tag_resources(
        ResourceARNList=[arn],
        Tags={"Monitoring": value},
    )
    failed = resp.get("FailedResourcesMap") or {}
    if failed:
        raise RuntimeError(f"Failed to tag {arn}: {failed}")


def _apply_alarms_for_toggle(resource: dict, monitoring: bool) -> None:
    """토글 즉시 알람 생성/삭제 — 다음 daily monitor 실행을 기다리지 않고 갭을 줄인다.

    인벤토리엔 태그가 없으므로 ON 시 {Monitoring: on} 최소 태그로 기본 임계치 알람을
    생성한다. 실제 Threshold_* 태그·타입별 디멘션 힌트(_api_type 등) 기반 정밀화는
    다음 daily monitor가 self-heal 한다(근사 생성 → 정밀화).
    """
    resource_id = resource.get("resource_id") or resource.get("id")
    resource_type = resource.get("type")
    session, region, _ = _resource_aws_session(resource)
    cw = (session.client("cloudwatch", region_name=region)
          if session is not None else _get_cw_client_for_region(region))
    if monitoring:
        sync_alarms_for_resource(resource_id, resource_type, {"Monitoring": "on"}, cw=cw)
    else:
        delete_alarms_for_resource(resource_id, resource_type, cw=cw)


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
