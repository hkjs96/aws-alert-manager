"""
ELBv2 수집기 — ALB·NLB·대상 그룹 셋을 한 모듈에서, 나열·메트릭 모두 타입 고유(오버라이드) (docs/specs/resource-type-registry P3)

나열: RGT 필터 `elasticloadbalancing:loadbalancer`는 CLB와 공유하고 LB↔TG 계층(대상 그룹은 연결된 LB의 ARN·종류를 내부 태그로
가져야 한다)과 삭제 중 상태 필터가 describe를 요구한다 — 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다(태그는
캐시에서). 한 번에 타입 셋(ALB·NLB·TG)을 내므로 항목이 `(TagName, tags, type)`이다. TagName = LB/TG ARN.
메트릭(오버라이드 `_metrics`): TG는 `lb_arn` 인자로 LoadBalancer 디멘션을 만들고 NLB 대상 그룹은 네임스페이스가 AWS/NetworkELB로
바뀐다. ALB `RequestCount`는 알람 정의에 없는 수집 전용 지표라 정의에서 만들 수 없다. daily_monitor가 TG에만 `lb_arn=`을 넘긴다.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common.collectors.base import CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM, collect_metric
from common.collectors.generic import GenericCollector
from common.resource_types.alb import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_elbv2_client():
    """ELBv2 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("elbv2")


def _enumerate() -> list[tuple[str, dict, str]]:
    """describe_load_balancers → 미삭제 LB 태그 → Monitoring=on LB와 그 아래 Monitoring=on 대상 그룹. (arn, tags, type)."""
    try:
        elbv2 = _get_elbv2_client()
        paginator = elbv2.get_paginator("describe_load_balancers")
        pages = list(paginator.paginate())
    except ClientError as e:
        logger.error("ELBv2 describe_load_balancers failed: %s", e)
        raise

    found: list[tuple[str, dict, str]] = []
    for page in pages:
        for lb in page.get("LoadBalancers", []):
            lb_arn = lb["LoadBalancerArn"]
            lb_state = lb.get("State", {}).get("Code", "")
            if lb_state in ("deleting", "deleted", "failed"):
                logger.info("Skipping LB %s: state=%s", lb_arn, lb_state)
                continue

            tags = _get_tags(elbv2, lb_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue   # 대상 그룹 나열을 아낀다 — 범용 수집기가 같은 필터를 다시 건다

            lb_type = lb.get("Type", "application")
            tags["_lb_type"] = lb_type
            found.append((lb_arn, tags, "ALB" if lb_type == "application" else "NLB"))
            found.extend(_target_groups(elbv2, lb_arn, lb_type))
    return found


def _target_groups(elbv2, lb_arn: str, lb_type: str) -> list[tuple[str, dict, str]]:
    """LB에 연결된 대상 그룹 중 Monitoring=on — 내부 태그 _lb_arn·_lb_type·_resource_subtype·_target_type 포함."""
    try:
        paginator = elbv2.get_paginator("describe_target_groups")
        pages = paginator.paginate(LoadBalancerArn=lb_arn)
    except ClientError as e:
        logger.error("describe_target_groups failed for LB %s: %s", lb_arn, e)
        return []

    found: list[tuple[str, dict, str]] = []
    for page in pages:
        for tg in page.get("TargetGroups", []):
            tg_arn = tg["TargetGroupArn"]
            tags = _get_tags(elbv2, tg_arn)
            if tags.get("Monitoring", "").lower() != "on":
                continue
            tags["_lb_arn"] = lb_arn
            tags["_lb_type"] = lb_type
            tags["_resource_subtype"] = "TG"
            tags["_target_type"] = tg.get("TargetType", "instance")
            found.append((tg_arn, tags, "TG"))
    return found


def _metrics(resource_id: str, resource_tags: dict | None = None,
             lb_arn: str | None = None) -> dict[str, float] | None:
    """
    CloudWatch에서 ELB/TG 메트릭 조회.

    ALB (_lb_type=application): RequestCount (Sum) → 'RequestCount'
    NLB (_lb_type=network): ProcessedBytes (Sum) → 'ProcessedBytes', ActiveFlowCount (Average), NewFlowCount (Sum)
    TG: RequestCount (Sum) → 'RequestCount', HealthyHostCount (Average) → 'HealthyHostCount'

    lb_arn: TG인 경우 연결된 LB ARN (TG Dimension에 필요). 수집된 메트릭 없으면 None.
    """
    if resource_tags is None:
        resource_tags = {}

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)
    metrics: dict[str, float] = {}

    is_tg = resource_tags.get("_resource_subtype") == "TG" or lb_arn is not None
    if is_tg and lb_arn:
        _collect_tg_metrics(resource_id, lb_arn, resource_tags, start_time, end_time, metrics)
    else:
        _collect_lb_metrics(resource_id, resource_tags, start_time, end_time, metrics)

    return metrics if metrics else None


def _collect_tg_metrics(tg_arn, lb_arn, resource_tags, start_time, end_time, metrics):
    """TG 레벨 메트릭 조회. lb_type에 따라 네임스페이스 분기."""
    tg_suffix = _arn_to_suffix(tg_arn)
    lb_suffix = _arn_to_suffix(lb_arn)
    lb_type = resource_tags.get("_lb_type", "application")
    namespace = _namespace_for_lb_type(lb_type)

    dim_tg = [
        {"Name": "TargetGroup", "Value": tg_suffix},
        {"Name": "LoadBalancer", "Value": lb_suffix},
    ]
    collect_metric(namespace, "RequestCount", dim_tg, start_time, end_time, "RequestCount",
                   metrics, stat=CW_STAT_SUM, resource_label="TG")
    collect_metric(namespace, "HealthyHostCount", dim_tg, start_time, end_time, "HealthyHostCount",
                   metrics, stat=CW_STAT_AVG, resource_label="TG")


def _collect_lb_metrics(resource_id, resource_tags, start_time, end_time, metrics):
    """LB 레벨 메트릭 조회. ALB/NLB에 따라 네임스페이스·메트릭 분기."""
    lb_suffix = _arn_to_suffix(resource_id)
    lb_type = resource_tags.get("_lb_type", "application")
    namespace = _namespace_for_lb_type(lb_type)
    dim_lb = [{"Name": "LoadBalancer", "Value": lb_suffix}]

    if lb_type == "network":
        collect_metric(namespace, "ProcessedBytes", dim_lb, start_time, end_time, "ProcessedBytes",
                       metrics, stat=CW_STAT_SUM, resource_label="ELB")
        collect_metric(namespace, "ActiveFlowCount", dim_lb, start_time, end_time, "ActiveFlowCount",
                       metrics, stat=CW_STAT_AVG, resource_label="ELB")
        collect_metric(namespace, "NewFlowCount", dim_lb, start_time, end_time, "NewFlowCount",
                       metrics, stat=CW_STAT_SUM, resource_label="ELB")
    else:
        collect_metric(namespace, "RequestCount", dim_lb, start_time, end_time, "RequestCount",
                       metrics, stat=CW_STAT_SUM, resource_label="ELB")


def _namespace_for_lb_type(lb_type: str) -> str:
    """LB 타입에 따른 CloudWatch 네임스페이스 반환."""
    if lb_type == "network":
        return "AWS/NetworkELB"
    return "AWS/ApplicationELB"


def _alive(tag_names: set[str]) -> set[str]:
    """ELB/TG 리소스 존재 여부 확인. resource_id가 ARN 형식이면 직접 조회, 아니면 보수적으로 alive 처리."""
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
                logger.error("describe_load_balancers failed for %s: %s", arn, e)

    for arn in tg_arns:
        try:
            elb_client.describe_target_groups(TargetGroupArns=[arn])
            alive.add(arn)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "TargetGroupNotFound":
                logger.info("TG not found (orphan): %s", arn)
            else:
                logger.error("describe_target_groups failed for %s: %s", arn, e)

    alive.update(other_ids)
    return alive


def _get_tags(elbv2_client, resource_arn: str) -> dict:
    cached = cached_tags(resource_arn)
    if cached is not None:
        return cached
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


# ALB 스펙에 묶는다 — 이 수집기는 ALB·NLB·TG 셋을 내며(_enumerate가 타입을 항목마다 준다) 스펙 셋이 collector="elb"로 이걸 가리킨다.
COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate, metrics=_metrics)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
