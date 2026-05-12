"""
/resources 엔드포인트

GET  /resources                    → 리소스 목록 (페이지네이션, 필터)
POST /resources/sync               → 리소스 동기화 트리거
GET  /resources/{id}               → 단일 리소스 상세
GET  /resources/{id}/alarms        → 리소스의 알람 설정 목록
POST /resources/{id}/alarms        → 알람 생성 (disk_used_percent는 mount_path 지원)
GET  /resources/{id}/disk-paths    → 인스턴스의 CWAgent 디스크 경로 목록
GET  /resources/{id}/metrics       → CloudWatch가 보고 중인 메트릭 카탈로그
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
    get_resources_from_alarms,
    list_alarms,
    extract_resource_from_alarm,
)
from common import dimension_builder
from common.alarm_naming import _build_alarm_description, _pretty_alarm_name
from common.alarm_registry import (
    _DIMENSION_KEY_MAP,
    _GLOBAL_SERVICE_REGION,
    _METRIC_DISPLAY,
    _NAMESPACE_MAP,
    _metric_name_to_key,
)

logger = logging.getLogger(__name__)

_LIST_METRICS_PAGE_CAP = 10  # NextToken 페이지 최대 개수 (~5000개 메트릭)


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))


@functools.lru_cache(maxsize=None)
def _get_cw_client_for_region(region: str):
    return boto3.client("cloudwatch", region_name=region)


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))


def list_resources(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    page = int(qs.get("page", 1))
    page_size = min(int(qs.get("page_size", 25)), 100)
    resource_type = qs.get("resource_type") or None
    search = qs.get("search") or None

    try:
        result = get_resources_from_alarms(
            page=page,
            page_size=page_size,
            resource_type=resource_type,
            search=search,
        )
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    return _ok(result)


def sync_resources(event: dict) -> dict:
    """
    리소스 동기화 트리거.
    Phase 1: daily_monitor Lambda를 직접 invoke 하거나 단순 응답 반환.
    Phase 2: SQS 비동기 작업으로 교체.
    """
    return _ok({
        "discovered": 0,
        "updated": 0,
        "removed": 0,
        "message": "동기화는 daily_monitor 스케줄 실행 시 자동 처리됩니다",
    })


def get_resource(event: dict) -> dict:
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    # resource_id(tag_name)로 알람 필터링
    resource_alarms = [
        a for a in alarms
        if _get_tag_name(a["AlarmName"]) == resource_id
    ]
    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"리소스 '{resource_id}'의 알람을 찾을 수 없습니다")

    resource_type = _get_resource_type(resource_alarms[0]["AlarmName"])
    region, account_id = _parse_alarm_arn(resource_alarms[0].get("AlarmArn", ""))
    active = sum(1 for a in resource_alarms if a.get("StateValue") == "ALARM")

    return _ok({
        "id": resource_id,
        "name": resource_id,
        "type": resource_type,
        "account": account_id,
        "region": region,
        "monitoring": True,
        "alarms": {"critical": active, "warning": 0},
        "alarm_count": len(resource_alarms),
    })


def get_resource_alarms(event: dict) -> dict:
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    resource_alarms = [
        a for a in alarms
        if _get_tag_name(a["AlarmName"]) == resource_id
    ]

    configs = []
    for alarm in resource_alarms:
        tags = {t["Key"]: t["Value"] for t in alarm.get("Tags", [])} if alarm.get("Tags") else {}
        configs.append({
            "alarm_name": alarm["AlarmName"],
            "metric_name": alarm.get("MetricName", ""),
            "namespace": alarm.get("Namespace", ""),
            "threshold": alarm.get("Threshold"),
            "comparison": alarm.get("ComparisonOperator", ""),
            "state": alarm.get("StateValue", ""),
            "severity": tags.get("Severity", "SEV-5"),
            "monitoring": True,
        })

    return _ok(configs)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

import re
_ALARM_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")


def _get_tag_name(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(2) if m else ""


def _get_resource_type(alarm_name: str) -> str:
    m = _ALARM_NAME_RE.match(alarm_name)
    return m.group(1) if m else ""


def get_resource_metrics(event: dict) -> dict:
    """리소스가 CloudWatch에 보고 중인 메트릭 카탈로그 조회.

    응답: [{namespace, metric_name, unit, direction, needs_mount_path}, ...]
    같은 (namespace, metric_name)은 1개로 dedupe. disk_used_percent처럼 path 변형이
    있는 항목은 needs_mount_path: true로 표시되며, 실제 path 목록은 /disk-paths 호출.
    """
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    resource_alarms = [a for a in alarms if _get_tag_name(a["AlarmName"]) == resource_id]
    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"리소스 '{resource_id}'를 찾을 수 없습니다")

    resource_type = _get_resource_type(resource_alarms[0]["AlarmName"])
    namespaces = _NAMESPACE_MAP.get(resource_type, [])
    dim_key = _DIMENSION_KEY_MAP.get(resource_type, "")
    if not namespaces or not dim_key:
        return _ok([])

    if resource_type in ("ALB", "NLB", "TG"):
        dim_value = dimension_builder._extract_elb_dimension(resource_id)
    else:
        dim_value = resource_id

    region = _GLOBAL_SERVICE_REGION.get(resource_type)
    cw = _get_cw_client_for_region(region) if region else _get_cw_client()

    seen: set[tuple[str, str]] = set()
    items: list[dict] = []
    for namespace in namespaces:
        try:
            for metric in _paginated_list_metrics(cw, namespace, dim_key, dim_value):
                metric_name = metric.get("MetricName", "")
                key = (namespace, metric_name)
                if key in seen:
                    continue
                seen.add(key)
                items.append(_metric_catalog_entry(namespace, metric_name, resource_type))
        except ClientError as e:
            logger.error("list_metrics 실패 (%s/%s): %s", namespace, dim_value, e)

    items.sort(key=lambda m: (m["namespace"], m["metric_name"]))
    return _ok(items)


def _paginated_list_metrics(cw, namespace: str, dim_key: str, dim_value: str):
    """list_metrics를 NextToken으로 순회. 페이지 cap 내에서만 응답을 yield."""
    next_token = None
    for _ in range(_LIST_METRICS_PAGE_CAP):
        kwargs = {
            "Namespace": namespace,
            "Dimensions": [{"Name": dim_key, "Value": dim_value}],
        }
        if next_token:
            kwargs["NextToken"] = next_token
        resp = cw.list_metrics(**kwargs)
        for m in resp.get("Metrics", []):
            yield m
        next_token = resp.get("NextToken")
        if not next_token:
            return


def _metric_catalog_entry(namespace: str, metric_name: str, resource_type: str) -> dict:
    """메트릭 1건의 카탈로그 응답 항목 생성. _METRIC_DISPLAY 미등록은 unit=null."""
    metric_key = _metric_name_to_key(metric_name)
    display = _METRIC_DISPLAY.get(metric_key)
    if display:
        _, direction, unit = display
    else:
        direction, unit = ">", None
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "unit": unit,
        "direction": direction,
        "needs_mount_path": resource_type == "EC2" and metric_name == "disk_used_percent",
    }


def get_disk_paths(event: dict) -> dict:
    """CWAgent가 보고하는 disk_used_percent path dimension 목록 반환."""
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    cw = _get_cw_client()
    try:
        resp = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
        )
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    paths = []
    seen = set()
    for m in resp.get("Metrics", []):
        path = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "path"), None)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)

    return _ok(sorted(paths))


def create_resource_alarm(event: dict) -> dict:
    """리소스에 알람 생성.

    - disk_used_percent: mount_path 필수, 기존 CWAgent path/device/fstype 디멘션 유지.
    - 그 외 메트릭: dimension_builder._resolve_metric_dimensions로 namespace/dimensions 자동 해석.
    """
    resource_id = (event.get("pathParameters") or {}).get("id", "")
    if not resource_id:
        return _err(400, "MISSING_PARAM", "resource_id가 필요합니다")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_BODY", "JSON 파싱 실패")

    metric_name = body.get("metric_name", "")
    threshold = body.get("threshold")
    mount_path = body.get("mount_path")
    severity = body.get("severity", "SEV-5")

    if not metric_name or threshold is None:
        return _err(400, "MISSING_PARAM", "metric_name, threshold는 필수입니다")
    if metric_name == "disk_used_percent" and not mount_path:
        return _err(400, "MISSING_PARAM", "disk_used_percent 알람은 mount_path가 필요합니다")

    # 리소스 타입 추론 (기존 알람에서)
    try:
        existing_alarms = list_alarms()
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    resource_alarms = [a for a in existing_alarms if _get_tag_name(a["AlarmName"]) == resource_id]
    if not resource_alarms:
        return _err(404, "NOT_FOUND", f"리소스 '{resource_id}'를 찾을 수 없습니다")
    resource_type = _get_resource_type(resource_alarms[0]["AlarmName"])

    region = _GLOBAL_SERVICE_REGION.get(resource_type)
    cw = _get_cw_client_for_region(region) if region else _get_cw_client()

    # 알람명: EC2는 인스턴스 Name 태그 조회, 그 외는 resource_id 사용
    resource_name = _get_instance_name(resource_id) if resource_type == "EC2" else ""

    if metric_name == "disk_used_percent":
        dims = _get_disk_dimensions_for_path(resource_id, mount_path, cw)
        if not dims:
            return _err(404, "NO_METRIC", f"'{mount_path}' 경로의 CWAgent 메트릭을 찾을 수 없습니다")
        namespace = "CWAgent"
        suffix = mount_path.lstrip("/") or "root"
        metric_key = f"disk_used_percent_{suffix}"
    else:
        resolved = dimension_builder._resolve_metric_dimensions(
            resource_id, metric_name, resource_type, cw=cw,
        )
        if not resolved:
            return _err(404, "NO_METRIC",
                        f"'{metric_name}' 메트릭을 CloudWatch에서 찾을 수 없습니다")
        namespace, dims = resolved
        metric_key = _metric_name_to_key(metric_name)

    alarm_name = _pretty_alarm_name(
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        metric=metric_key,
        threshold=float(threshold),
    )
    description = _build_alarm_description(
        resource_type=resource_type,
        resource_id=resource_id,
        metric_key=metric_key,
    )

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
    except ClientError as e:
        return _err(500, "CW_ERROR", str(e))

    return _ok({"alarm_name": alarm_name, "metric_name": metric_name, "mount_path": mount_path}, status=201)


def _get_instance_name(instance_id: str) -> str:
    try:
        ec2 = _get_ec2_client()
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        tags = resp["Reservations"][0]["Instances"][0].get("Tags", [])
        name_tag = next((t["Value"] for t in tags if t["Key"] == "Name"), "")
        return name_tag
    except (ClientError, IndexError, KeyError):
        return ""


def _get_disk_dimensions_for_path(instance_id: str, mount_path: str, cw) -> list[dict]:
    """특정 mount_path의 CWAgent dimension 조합 반환."""
    try:
        resp = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        )
    except ClientError:
        return []

    _DISK_DIM_KEYS = {"InstanceId", "device", "fstype", "path"}
    for m in resp.get("Metrics", []):
        path = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "path"), None)
        if path == mount_path:
            return [d for d in m["Dimensions"] if d["Name"] in _DISK_DIM_KEYS]
    return []


def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}
