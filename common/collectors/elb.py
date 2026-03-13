"""
ELBCollector - Requirements 1.1, 1.2, 1.5, 3.5

Monitoring=on 태그가 있는 ALB 및 TargetGroup 수집 및 CloudWatch 메트릭 조회.
ALB 레벨: RequestCount
TG 레벨: RequestCount, HealthyHostCount (TG에 Monitoring=on 태그 있을 때만)
"""

import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo

logger = logging.getLogger(__name__)

_CW_PERIOD = 300
_CW_STAT_SUM = "Sum"
_CW_STAT_AVG = "Average"
_CW_LOOKBACK_MINUTES = 10


def collect_monitored_resources() -> list[ResourceInfo]:
    """
    Monitoring=on 태그가 있는 ALB 목록 반환.
    각 ALB에 연결된 TG 중 Monitoring=on 태그 있는 것도 포함.
    삭제 중인 ALB는 제외하고 로그 기록.

    Returns:
        ALB + TG ResourceInfo 리스트. type은 'ELB' 또는 'TG'.
    """
    try:
        elbv2 = boto3.client("elbv2")
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
                logger.info("Skipping ALB %s: state=%s", lb_arn, lb_state)
                continue

            tags = _get_tags(elbv2, lb_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue

            resources.append(
                ResourceInfo(
                    id=lb_arn,
                    type="ELB",
                    tags=tags,
                    region=region,
                )
            )

            # ALB에 연결된 TG 중 Monitoring=on 태그 있는 것 수집
            tg_resources = _collect_target_groups(elbv2, lb_arn, region)
            resources.extend(tg_resources)

    return resources


def get_metrics(resource_id: str, resource_tags: dict | None = None,
                lb_arn: str | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 ELB/TG 메트릭 조회.

    ALB (type=ELB):
    - RequestCount (Sum) → 'RequestCount'

    TG (type=TG):
    - RequestCount (Sum) → 'RequestCount'
    - HealthyHostCount (Average) → 'HealthyHostCount'

    Args:
        resource_id: ALB ARN 또는 TG ARN
        resource_tags: 리소스 태그
        lb_arn: TG인 경우 연결된 ALB ARN (TG Dimension에 필요)

    Returns:
        {metric_name: value} 딕셔너리. 수집된 메트릭 없으면 None.
    """
    if resource_tags is None:
        resource_tags = {}

    cw = boto3.client("cloudwatch")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=_CW_LOOKBACK_MINUTES)

    metrics: dict[str, float] = {}
    is_tg = resource_tags.get("_resource_subtype") == "TG" or lb_arn is not None

    if is_tg and lb_arn:
        # TG ARN suffix 추출 (arn:aws:elasticloadbalancing:...:targetgroup/name/id → targetgroup/name/id)
        tg_suffix = _arn_to_suffix(resource_id)
        lb_suffix = _arn_to_suffix(lb_arn)

        dim_tg = [
            {"Name": "TargetGroup", "Value": tg_suffix},
            {"Name": "LoadBalancer", "Value": lb_suffix},
        ]
        _collect_metric(cw, "AWS/ApplicationELB", "RequestCount", dim_tg,
                        start_time, end_time, "RequestCount", metrics, _CW_STAT_SUM)
        _collect_metric(cw, "AWS/ApplicationELB", "HealthyHostCount", dim_tg,
                        start_time, end_time, "HealthyHostCount", metrics, _CW_STAT_AVG)
    else:
        # ALB 레벨
        lb_suffix = _arn_to_suffix(resource_id)
        dim_lb = [{"Name": "LoadBalancer", "Value": lb_suffix}]
        _collect_metric(cw, "AWS/ApplicationELB", "RequestCount", dim_lb,
                        start_time, end_time, "RequestCount", metrics, _CW_STAT_SUM)

    return metrics if metrics else None


def _collect_target_groups(elbv2, lb_arn: str, region: str) -> list[ResourceInfo]:
    """ALB에 연결된 TG 중 Monitoring=on 태그 있는 것 반환."""
    try:
        paginator = elbv2.get_paginator("describe_target_groups")
        pages = paginator.paginate(LoadBalancerArn=lb_arn)
    except ClientError as e:
        logger.error("describe_target_groups failed for ALB %s: %s", lb_arn, e)
        return []

    tg_resources = []
    for page in pages:
        for tg in page.get("TargetGroups", []):
            tg_arn = tg["TargetGroupArn"]
            tags = _get_tags(elbv2, tg_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue
            # lb_arn을 태그에 저장해 get_metrics에서 사용
            tags["_lb_arn"] = lb_arn
            tags["_resource_subtype"] = "TG"
            tg_resources.append(
                ResourceInfo(
                    id=tg_arn,
                    type="TG",
                    tags=tags,
                    region=region,
                )
            )
    return tg_resources


def _collect_metric(cw, namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict, stat):
    value = _query_metric(cw, namespace, cw_metric_name, dimensions, start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric: no data (dimensions=%s)", result_key, dimensions)


def _query_metric(cw, namespace, metric_name, dimensions,
                  start_time, end_time, stat) -> float | None:
    try:
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=_CW_PERIOD,
            Statistics=[stat],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        latest = max(datapoints, key=lambda d: d["Timestamp"])
        return latest[stat]
    except ClientError as e:
        logger.error("CloudWatch query failed for %s/%s: %s", namespace, metric_name, e)
        return None


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
    TG:   arn:...:targetgroup/my-tg/abc123        → targetgroup/my-tg/abc123
    """
    # ARN 마지막 콜론 이후 부분에서 첫 번째 슬래시 앞 prefix 제거
    # loadbalancer/app/... → app/...
    # targetgroup/... → targetgroup/...
    resource_part = arn.split(":")[-1]  # e.g. "loadbalancer/app/my-alb/id"
    if resource_part.startswith("loadbalancer/"):
        return resource_part[len("loadbalancer/"):]
    return resource_part
