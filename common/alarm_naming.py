"""
Alarm Naming — 알람 이름 생성, 메타데이터 빌드/파싱, Short ID 추출

알람 이름 포맷, AlarmDescription JSON 메타데이터, ALB/NLB/TG ARN Short ID를 전담한다.
"""

import json
import logging
import os

from common.alarm_registry import _METRIC_DISPLAY

logger = logging.getLogger(__name__)


def _get_env() -> str:
    return os.environ.get("ENVIRONMENT", "prod")


def _alarm_name(resource_id: str, metric: str) -> str:
    """레거시 알람 이름 생성 (삭제 호환용): {resource_id}-{metric}-{env}"""
    return f"{resource_id}-{metric}-{_get_env()}"


def _shorten_elb_resource_id(resource_id: str, resource_type: str) -> str:
    """ALB/NLB/TG ARN에서 짧은 식별자(name/hash)를 추출.

    - ALB: arn:...loadbalancer/app/{name}/{hash} → {name}/{hash}
    - NLB: arn:...loadbalancer/net/{name}/{hash} → {name}/{hash}
    - TG:  arn:...targetgroup/{name}/{hash}      → {name}/{hash}
    - EC2/RDS 또는 ARN이 아닌 입력: 그대로 반환 (방어적 처리)
    """
    if resource_type not in ("ALB", "NLB", "TG"):
        return resource_id
    if not resource_id:
        return resource_id

    if resource_type in ("ALB", "NLB"):
        # loadbalancer/app/{name}/{hash} 또는 loadbalancer/net/{name}/{hash}
        for prefix in ("loadbalancer/app/", "loadbalancer/net/"):
            idx = resource_id.find(prefix)
            if idx >= 0:
                return resource_id[idx + len(prefix):]
    elif resource_type == "TG":
        # targetgroup/{name}/{hash}
        marker = ":targetgroup/"
        idx = resource_id.find(marker)
        if idx >= 0:
            return resource_id[idx + len(marker):]
        # 이미 short_id 형태이거나 "targetgroup/" 접두사 없는 경우
        marker_no_colon = "targetgroup/"
        if resource_id.startswith(marker_no_colon):
            return resource_id[len(marker_no_colon):]

    return resource_id


def _pretty_alarm_name(
    resource_type: str,
    resource_id: str,
    resource_name: str,
    metric: str,
    threshold: float,
) -> str:
    """
    알람 이름 생성 (새 포맷).
    [EC2] my-server CPU >80% (i-0fd4bf757020d3714)

    255자 초과 시 label → display_metric 순으로 truncate.
    resource_id 부분은 알람 검색/매칭에 필수이므로 절대 truncate하지 않음.
    """
    _MAX_ALARM_NAME = 255
    _ELLIPSIS = "..."

    direction, unit = _METRIC_DISPLAY.get(
        metric.split("-")[0] if metric.startswith("Disk-") else metric,
        ("unknown", ">", ""),
    )[1:]
    display_name = _METRIC_DISPLAY.get(
        metric.split("-")[0] if metric.startswith("Disk-") else metric,
        ("unknown", ">", ""),
    )[0]
    # Disk-root → disk_used_percent(/) , Disk-data → disk_used_percent(/data)
    if metric.startswith("Disk-"):
        path_part = metric[len("Disk-"):]
        display_metric = f"{display_name}(/{path_part})" if path_part != "root" else f"{display_name}(/)"
    else:
        display_metric = display_name

    # threshold 표시: 정수면 소수점 없이, 소수면 불필요한 0 제거
    if threshold == int(threshold):
        thr_str = str(int(threshold))
    else:
        thr_str = f"{threshold:g}"

    label = resource_name or resource_id

    # 고정 부분 (절대 truncate 불가): prefix + threshold_part + suffix
    prefix = f"[{resource_type}] "
    threshold_part = f" {direction}{thr_str}{unit} "
    short_id = _shorten_elb_resource_id(resource_id, resource_type)
    suffix = f"({short_id})"

    fixed_len = len(prefix) + len(threshold_part) + len(suffix)
    available = _MAX_ALARM_NAME - fixed_len

    # 1단계: label + display_metric이 available 이내면 그대로
    if len(label) + 1 + len(display_metric) <= available:
        return f"{prefix}{label} {display_metric}{threshold_part}{suffix}"

    # 2단계: label truncate (display_metric 보존)
    # " " + display_metric 공간 확보
    label_budget = available - 1 - len(display_metric)
    if label_budget >= len(_ELLIPSIS) + 1:
        truncated_label = label[: label_budget - len(_ELLIPSIS)] + _ELLIPSIS
        return f"{prefix}{truncated_label} {display_metric}{threshold_part}{suffix}"

    # 3단계: label을 최소("...")로 고정하고 display_metric도 truncate
    min_label = _ELLIPSIS
    metric_budget = available - len(min_label) - 1
    if metric_budget >= len(_ELLIPSIS) + 1:
        truncated_metric = display_metric[: metric_budget - len(_ELLIPSIS)] + _ELLIPSIS
        return f"{prefix}{min_label} {truncated_metric}{threshold_part}{suffix}"

    # 4단계: 극단적 케이스 — label/display_metric 모두 최소
    return f"{prefix}{min_label} {_ELLIPSIS}{threshold_part}{suffix}"


def _build_alarm_description(
    resource_type: str,
    resource_id: str,
    metric_key: str,
    human_prefix: str = "",
) -> str:
    """AlarmDescription에 JSON 메타데이터를 포함하여 생성.

    포맷: {human_prefix} | {"metric_key":"CPU","resource_id":"i-xxx","resource_type":"EC2"}
    최대 1024자 (CloudWatch API 제한).
    """
    metadata = json.dumps({
        "metric_key": metric_key,
        "resource_id": resource_id,
        "resource_type": resource_type,
    }, separators=(",", ":"))
    if human_prefix:
        desc = f"{human_prefix} | {metadata}"
    else:
        desc = metadata
    return desc[:1024]


def _parse_alarm_metadata(description: str) -> dict | None:
    """AlarmDescription에서 JSON 메타데이터를 파싱.

    Returns:
        {"metric_key": ..., "resource_id": ..., "resource_type": ...} 또는 None
    """
    if not description:
        return None
    # JSON은 " | " 구분자 뒤에 위치
    idx = description.rfind(" | {")
    json_str = description[idx + 3:] if idx >= 0 else description
    try:
        data = json.loads(json_str)
        if "metric_key" in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None
