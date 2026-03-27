"""
Dimension Builder — CloudWatch 디멘션/네임스페이스 빌드

CloudWatch 디멘션 구성과 네임스페이스 해석을 전담한다.
"""

import logging

from botocore.exceptions import ClientError

import common._clients as _clients
from common.alarm_registry import _DIMENSION_KEY_MAP, _NAMESPACE_MAP

logger = logging.getLogger(__name__)


def _extract_elb_dimension(elb_arn: str) -> str:
    """
    ALB/NLB/TG ARN에서 CloudWatch Dimension 값 추출.
    arn:aws:elasticloadbalancing:...:loadbalancer/app/my-alb/1234
    → app/my-alb/1234
    arn:aws:elasticloadbalancing:...:targetgroup/my-tg/1234
    → targetgroup/my-tg/1234
    """
    # LB: loadbalancer/ prefix 제거 → app/... 또는 net/...
    parts = elb_arn.split("loadbalancer/", 1)
    if len(parts) == 2:
        return parts[1]
    # TG: targetgroup/ prefix 유지 (CloudWatch 디멘션 규칙)
    parts = elb_arn.split(":targetgroup/", 1)
    if len(parts) == 2:
        return "targetgroup/" + parts[1]
    return elb_arn


def _build_dimensions(
    alarm_def: dict,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> list[dict]:
    """리소스 유형별 CloudWatch Dimensions 리스트 생성.

    - TG: TargetGroup + LoadBalancer 복합 디멘션
    - ALB/NLB: LoadBalancer 단일 디멘션
    - EC2/RDS 등: {dim_key: resource_id} 단일 디멘션
    - alarm_def의 extra_dimensions 추가
    """
    dim_key = alarm_def["dimension_key"]

    if resource_type == "TG":
        dimensions = [
            {"Name": "TargetGroup", "Value": _extract_elb_dimension(resource_id)},
            {"Name": "LoadBalancer", "Value": _extract_elb_dimension(resource_tags["_lb_arn"])},
        ]
    elif resource_type in ("ALB", "NLB"):
        dimensions = [{"Name": dim_key, "Value": _extract_elb_dimension(resource_id)}]
    else:
        dimensions = [{"Name": dim_key, "Value": resource_id}]

    dimensions.extend(alarm_def.get("extra_dimensions", []))
    return dimensions


def _resolve_tg_namespace(alarm_def: dict, resource_tags: dict) -> str:
    """TG 리소스의 CloudWatch namespace를 동적 결정.

    _lb_type == "network" → AWS/NetworkELB, 그 외 → alarm_def["namespace"].
    """
    if resource_tags.get("_lb_type") == "network":
        return "AWS/NetworkELB"
    return alarm_def["namespace"]


def _select_best_dimensions(
    metrics: list[dict],
    primary_dim_key: str,
) -> list[dict]:
    """list_metrics 결과에서 최적 디멘션 조합 선택.

    우선순위:
    1. Primary_Dimension_Key만 포함된 조합
    2. AZ 미포함 + 디멘션 수 최소
    3. 디멘션 수 최소 (AZ 포함 허용)
    """
    if not metrics:
        return []

    # 1순위: primary_dim_key만 포함된 조합
    for m in metrics:
        dims = m["Dimensions"]
        if len(dims) == 1 and dims[0]["Name"] == primary_dim_key:
            return dims

    # 2순위: AZ 미포함 조합 중 디멘션 수 최소
    no_az = [
        m["Dimensions"] for m in metrics
        if not any(d["Name"] == "AvailabilityZone" for d in m["Dimensions"])
    ]
    if no_az:
        return min(no_az, key=len)

    # 3순위: 디멘션 수 최소 (AZ 포함 허용)
    return min((m["Dimensions"] for m in metrics), key=len)


def _resolve_metric_dimensions(
    resource_id: str,
    metric_name: str,
    resource_type: str,
    *,
    cw=None,
) -> tuple[str, list[dict]] | None:
    """list_metrics API로 네임스페이스/디멘션 자동 해석.

    Args:
        resource_id: 리소스 ID
        metric_name: CloudWatch 메트릭 이름
        resource_type: EC2 / RDS / ELB

    Returns:
        (namespace, dimensions) 튜플 또는 None (미발견 시)
    """
    cw = cw or _clients._get_cw_client()
    namespaces = _NAMESPACE_MAP.get(resource_type, [])
    dim_key = _DIMENSION_KEY_MAP.get(resource_type, "")

    # ALB/NLB/TG는 ARN suffix를 디멘션 값으로 사용
    if resource_type in ("ALB", "NLB", "TG"):
        dim_value = _extract_elb_dimension(resource_id)
    else:
        dim_value = resource_id

    for namespace in namespaces:
        try:
            resp = cw.list_metrics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[
                    {"Name": dim_key, "Value": dim_value},
                ],
            )
            metrics = resp.get("Metrics", [])
            if metrics:
                return (namespace, _select_best_dimensions(metrics, dim_key))
        except ClientError as e:
            logger.error(
                "Failed to list_metrics for %s/%s (%s): %s",
                namespace, metric_name, resource_id, e,
            )

    logger.warning(
        "Metric %s not found in any namespace for %s (%s): skipping",
        metric_name, resource_id, resource_type,
    )
    return None


def _get_disk_dimensions(instance_id: str, extra_paths: set[str] | None = None, *, cw=None) -> list[list[dict]]:
    """
    CloudWatch에서 해당 인스턴스의 실제 disk_used_percent dimension 조합 조회.

    기본적으로 '/' (root)만 반환.
    extra_paths에 추가 경로가 있으면 해당 경로도 포함.

    Args:
        instance_id: EC2 인스턴스 ID
        extra_paths: 태그 기반 추가 모니터링 경로 (예: {"/data", "/var"})

    Returns:
        dimension 조합 리스트. 조회 실패 또는 메트릭 없으면 빈 리스트 반환.
    """
    target_paths = {"/"}
    if extra_paths:
        target_paths.update(extra_paths)

    cw = cw or _clients._get_cw_client()
    try:
        resp = cw.list_metrics(
            Namespace="CWAgent",
            MetricName="disk_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        )
        metrics = resp.get("Metrics", [])
        if not metrics:
            logger.warning(
                "No CWAgent disk_used_percent metrics found for %s. "
                "CWAgent may not be installed or not yet reporting.",
                instance_id,
            )
            return []

        # path 기준으로 필터링 (target_paths에 있는 것만) + 중복 제거
        seen_paths = set()
        result = []
        for m in metrics:
            path = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "path"), None)
            if path and path in target_paths and path not in seen_paths:
                seen_paths.add(path)
                result.append(m["Dimensions"])

        missing = target_paths - seen_paths
        if missing:
            logger.warning(
                "Disk paths not found in CWAgent metrics for %s: %s",
                instance_id, missing,
            )
        return result
    except ClientError as e:
        logger.error("Failed to list disk metrics for %s: %s", instance_id, e)
        return []
