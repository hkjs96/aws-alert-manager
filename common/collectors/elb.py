"""
ELBCollector - Requirements 1.1, 1.2, 1.5, 1.12, 2.12, 3.5

Monitoring=on 태그가 있는 ALB/NLB 및 TargetGroup 수집 및 CloudWatch 메트릭 조회.
ALB 레벨: RequestCount (AWS/ApplicationELB)
NLB 레벨: ProcessedBytes, ActiveFlowCount, NewFlowCount (AWS/NetworkELB)
TG 레벨: RequestCount, HealthyHostCount (TG에 Monitoring=on 태그 있을 때만)
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import (
    query_metric,
    CW_LOOKBACK_MINUTES,
    CW_STAT_AVG,
    CW_STAT_SUM,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_elbv2_client():
    """ELBv2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elbv2")


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 ALB/NLB 목록 반환.
    각 LB에 연결된 TG 중 Monitoring=on 태그 있는 것도 포함.
    삭제 중인 LB는 제외하고 로그 기록.

    Returns:
        ALB/NLB + TG ResourceInfo 리스트. type은 'ALB', 'NLB' 또는 'TG'.
        tags에 _lb_type ('application' 또는 'network') 포함.
    """
    try:
        elbv2 = _get_elbv2_client()
        paginator = elbv2.get_paginator("describe_load_balancers")
        pages = list(paginator.paginate())
    except ClientError as e:
        logger.error("ELBv2 describe_load_balancers failed: %s", e)
        raise

    resources: list[ResourceInfo] = []
    region = boto3.session.Session().region_name or "us-east-1"

    for page in pages:
        for lb in page.get("LoadBalancers", []):
            lb_arn = lb["LoadBalancerArn"]
            lb_state = lb.get("State", {}).get("Code", "")

            if lb_state in ("deleting", "deleted", "failed"):
                logger.info("Skipping LB %s: state=%s", lb_arn, lb_state)
                continue

            tags = _get_tags(elbv2, lb_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            # ALB/NLB 타입 저장 (기본값: application)
            lb_type = lb.get("Type", "application")
            tags["_lb_type"] = lb_type
            resource_type = "ALB" if lb_type == "application" else "NLB"

            resources.append(
                ResourceInfo(
                    id=lb_arn,
                    type=resource_type,
                    tags=tags,
                    region=region,
                )
            )

            # LB에 연결된 TG 중 Monitoring=on 태그 있는 것 수집
            tg_resources = _collect_target_groups(
                elbv2, lb_arn, region, lb_type,
            )
            resources.extend(tg_resources)

    return resources


def get_metrics(resource_id: str, resource_tags: dict | None = None,
                lb_arn: str | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 ELB/TG 메트릭 조회.

    ALB (type=ELB, _lb_type=application):
    - RequestCount (Sum) → 'RequestCount'

    NLB (type=ELB, _lb_type=network):
    - ProcessedBytes (Sum) → 'ProcessedBytes'
    - ActiveFlowCount (Average) → 'ActiveFlowCount'
    - NewFlowCount (Sum) → 'NewFlowCount'

    TG (type=TG):
    - RequestCount (Sum) → 'RequestCount'
    - HealthyHostCount (Average) → 'HealthyHostCount'

    Args:
        resource_id: ALB/NLB ARN 또는 TG ARN
        resource_tags: 리소스 태그 (_lb_type 포함)
        lb_arn: TG인 경우 연결된 LB ARN (TG Dimension에 필요)

    Returns:
        {metric_name: value} 딕셔너리. 수집된 메트릭 없으면 None.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)

    metrics: dict[str, float] = {}
    is_tg = (
        resource_tags.get("_resource_subtype") == "TG"
        or lb_arn is not None
    )

    if is_tg and lb_arn:
        _collect_tg_metrics(
            resource_id, lb_arn, resource_tags,
            start_time, end_time, metrics,
        )
    else:
        _collect_lb_metrics(
            resource_id, resource_tags,
            start_time, end_time, metrics,
        )

    return metrics if metrics else None


def _collect_tg_metrics(tg_arn, lb_arn, resource_tags,
                        start_time, end_time, metrics):
    """TG 레벨 메트릭 조회. lb_type에 따라 네임스페이스 분기."""
    tg_suffix = _arn_to_suffix(tg_arn)
    lb_suffix = _arn_to_suffix(lb_arn)
    lb_type = resource_tags.get("_lb_type", "application")
    namespace = _namespace_for_lb_type(lb_type)

    dim_tg = [
        {"Name": "TargetGroup", "Value": tg_suffix},
        {"Name": "LoadBalancer", "Value": lb_suffix},
    ]
    _collect_metric(namespace, "RequestCount", dim_tg,
                    start_time, end_time, "RequestCount",
                    metrics, CW_STAT_SUM)
    _collect_metric(namespace, "HealthyHostCount", dim_tg,
                    start_time, end_time, "HealthyHostCount",
                    metrics, CW_STAT_AVG)


def _collect_lb_metrics(resource_id, resource_tags,
                        start_time, end_time, metrics):
    """LB 레벨 메트릭 조회. ALB/NLB에 따라 네임스페이스·메트릭 분기."""
    lb_suffix = _arn_to_suffix(resource_id)
    lb_type = resource_tags.get("_lb_type", "application")
    namespace = _namespace_for_lb_type(lb_type)
    dim_lb = [{"Name": "LoadBalancer", "Value": lb_suffix}]

    if lb_type == "network":
        _collect_metric(namespace, "ProcessedBytes", dim_lb,
                        start_time, end_time, "ProcessedBytes",
                        metrics, CW_STAT_SUM)
        _collect_metric(namespace, "ActiveFlowCount", dim_lb,
                        start_time, end_time, "ActiveFlowCount",
                        metrics, CW_STAT_AVG)
        _collect_metric(namespace, "NewFlowCount", dim_lb,
                        start_time, end_time, "NewFlowCount",
                        metrics, CW_STAT_SUM)
    else:
        _collect_metric(namespace, "RequestCount", dim_lb,
                        start_time, end_time, "RequestCount",
                        metrics, CW_STAT_SUM)


def _namespace_for_lb_type(lb_type: str) -> str:
    """LB 타입에 따른 CloudWatch 네임스페이스 반환."""
    if lb_type == "network":
        return "AWS/NetworkELB"
    return "AWS/ApplicationELB"


def _collect_target_groups(elbv2, lb_arn: str,
                          region: str, lb_type: str) -> list[ResourceInfo]:
    """LB에 연결된 TG 중 Monitoring=on 태그 있는 것 반환."""
    try:
        paginator = elbv2.get_paginator("describe_target_groups")
        pages = paginator.paginate(LoadBalancerArn=lb_arn)
    except ClientError as e:
        logger.error("describe_target_groups failed for LB %s: %s",
                     lb_arn, e)
        return []

    tg_resources = []
    for page in pages:
        for tg in page.get("TargetGroups", []):
            tg_arn = tg["TargetGroupArn"]
            tags = _get_tags(elbv2, tg_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue
            # lb_arn과 lb_type을 태그에 저장해 get_metrics에서 사용
            tags["_lb_arn"] = lb_arn
            tags["_lb_type"] = lb_type
            tags["_resource_subtype"] = "TG"
            tags["_target_type"] = tg.get("TargetType", "instance")
            tg_resources.append(
                ResourceInfo(
                    id=tg_arn,
                    type="TG",
                    tags=tags,
                    region=region,
                )
            )
    return tg_resources


def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    """단일 메트릭 조회 후 metrics_dict에 추가. 데이터 없으면 skip."""
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric: no data (dimensions=%s)", result_key, dimensions)


def resolve_alive_ids(tag_names: set[str]) -> set[str]:
    """ELB/TG 리소스 존재 여부 확인.

    resource_id가 ARN 형식이면 직접 조회, 아니면 보수적으로 alive 처리.
    """
    elb_client = _get_elbv2_client()
    alive: set[str] = set()

    lb_arns = [r for r in tag_names if ":loadbalancer/" in r]
    tg_arns = [r for r in tag_names if ":targetgroup/" in r]
    other_ids = tag_names - set(lb_arns) - set(tg_arns)

    for arn in lb_arns:
        try:
            elb_client.describe_load_balancers(LoadBalancerArns=[arn])
            alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "LoadBalancerNotFound":
                logger.info("ELB not found (orphan): %s", arn)
            else:
                logger.error(
                    "describe_load_balancers failed for %s: %s", arn, e,
                )

    for arn in tg_arns:
        try:
            elb_client.describe_target_groups(TargetGroupArns=[arn])
            alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "TargetGroupNotFound":
                logger.info("TG not found (orphan): %s", arn)
            else:
                logger.error(
                    "describe_target_groups failed for %s: %s", arn, e,
                )

    # ARN이 아닌 ID — 존재 확인 불가, 보수적으로 alive 처리
    alive.update(other_ids)

    return alive


def _get_tags(elbv2_client, resource_arn: str) -> dict:
    try:
        response = elbv2_client.describe_tags(ResourceArns=[resource_arn])
        descriptions = response.get("TagDescriptions", [])
        if not descriptions:
            return {}
        return {t["Key"]: t["Value"] for t in descriptions[0].get("Tags", [])}
    except ClientError as e:
        logger.error("describe_tags failed for %s: %s", resource_arn, e)
        return {}


def _arn_to_suffix(arn: str) -> str:
    """
    ARN에서 CloudWatch Dimension 값으로 사용할 suffix 추출.

    ALB:  arn:...:loadbalancer/app/my-alb/abc123  → app/my-alb/abc123
    NLB:  arn:...:loadbalancer/net/my-nlb/abc123  → net/my-nlb/abc123
    TG:   arn:...:targetgroup/my-tg/abc123        → targetgroup/my-tg/abc123
    """
    resource_part = arn.split(":")[-1]  # e.g. "loadbalancer/app/my-alb/id"
    if resource_part.startswith("loadbalancer/"):
        return resource_part[len("loadbalancer/"):]
    return resource_part
