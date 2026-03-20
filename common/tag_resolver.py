"""
Tag_Resolver 모듈 - Requirements 2.1, 2.2, 2.3, 2.4, 2.5

태그 → 환경 변수 → 하드코딩 기본값 순으로 임계치를 조회하는 모듈.
향후 DB 교체를 고려한 인터페이스 제공.
"""

import functools
import logging
import os

import boto3
from botocore.exceptions import ClientError

from common import HARDCODED_DEFAULTS

logger = logging.getLogger(__name__)


def get_threshold(resource_tags: dict, metric_name: str) -> float:
    """
    리소스 태그에서 임계치를 조회.

    조회 우선순위: 태그 값 → 환경 변수 기본값 → 시스템 하드코딩 기본값.
    어떤 경우에도 유효한 양의 숫자(> 0)를 반환하며,
    절대 None을 반환하거나 예외를 발생시키지 않는다.

    Args:
        resource_tags: 리소스에 부착된 태그 딕셔너리
        metric_name: 메트릭 이름
            'CPU' | 'Memory' | 'Connections' | 'FreeMemoryGB' | 'FreeStorageGB'
            | 'RequestCount' | 'HealthyHostCount'
            | 'Disk_root' | 'Disk_data' | 'Disk_{path_key}' (Disk 계열)

    Returns:
        유효한 양의 숫자 임계치 값
    """
    # Disk 계열은 환경변수/하드코딩 폴백 시 'Disk' 기본 키 사용
    base_metric = "Disk" if metric_name.startswith("Disk_") else metric_name

    # 1단계: 태그에서 조회 (Threshold_{metric_name})
    tag_key = f"Threshold_{metric_name}"
    tag_value = resource_tags.get(tag_key)
    if tag_value is not None:
        try:
            val = float(tag_value)
            if val > 0:
                return val
            else:
                logger.warning(
                    "Invalid threshold tag %s=%r (not positive): falling back to env var",
                    tag_key, tag_value,
                )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid threshold tag %s=%r (non-numeric): falling back to env var",
                tag_key, tag_value,
            )

    # 2단계: 환경 변수에서 조회 (DEFAULT_{BASE_METRIC}_THRESHOLD)
    env_key = f"DEFAULT_{base_metric.upper()}_THRESHOLD"
    env_value = os.environ.get(env_key)
    if env_value is not None:
        try:
            val = float(env_value)
            if val > 0:
                return val
            else:
                logger.warning(
                    "Invalid env var %s=%r (not positive): falling back to hardcoded default",
                    env_key, env_value,
                )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid env var %s=%r (non-numeric): falling back to hardcoded default",
                env_key, env_value,
            )

    # 3단계: 시스템 하드코딩 기본값 (최종 폴백)
    default = HARDCODED_DEFAULTS.get(base_metric)
    if default is not None:
        return default

    logger.warning(
        "Unknown metric_name %r not in HARDCODED_DEFAULTS: returning 80.0",
        metric_name,
    )
    return 80.0


def get_disk_thresholds(resource_tags: dict) -> dict[str, float]:
    """
    태그에서 Threshold_Disk_* 패턴을 모두 스캔하여 {path: threshold} 딕셔너리 반환.

    예: {"Threshold_Disk_root": "85", "Threshold_Disk_data": "90"}
        → {"/": 85.0, "/data": 90.0}

    태그가 없으면 빈 딕셔너리 반환 (Collector에서 CWAgent 메트릭 skip 처리).
    """
    result = {}
    for key, value in resource_tags.items():
        if not key.startswith("Threshold_Disk_"):
            continue
        suffix = key[len("Threshold_Disk_"):]
        if not suffix:
            continue
        try:
            val = float(value)
            if val > 0:
                path = tag_suffix_to_disk_path(suffix)
                result[path] = val
            else:
                logger.warning("Invalid Disk threshold tag %s=%r (not positive): skipping", key, value)
        except (ValueError, TypeError):
            logger.warning("Invalid Disk threshold tag %s=%r (non-numeric): skipping", key, value)
    return result


def disk_path_to_tag_suffix(path: str) -> str:
    """
    경로를 태그 suffix로 변환.
    '/' → 'root', '/data' → 'data', '/var/log' → 'var_log'
    """
    if path == "/":
        return "root"
    # 선행 슬래시 제거 후 내부 슬래시를 언더스코어로
    return path.lstrip("/").replace("/", "_")


def tag_suffix_to_disk_path(suffix: str) -> str:
    """
    태그 suffix를 경로로 역변환.
    'root' → '/', 'data' → '/data', 'var_log' → '/var_log'
    참고: 언더스코어는 슬래시로 복원하지 않음 (단순 경로명 매핑)
    """
    if suffix == "root":
        return "/"
    return f"/{suffix}"


def has_monitoring_tag(resource_tags: dict) -> bool:
    """
    Monitoring=on 태그 존재 여부 반환.

    Args:
        resource_tags: 리소스에 부착된 태그 딕셔너리

    Returns:
        Monitoring=on 태그가 있으면 True, 없으면 False
    """
    return resource_tags.get("Monitoring", "").lower() == "on"


def get_resource_tags(resource_id: str, resource_type: str) -> dict:
    """
    AWS API를 통해 리소스 태그 조회.

    Args:
        resource_id: 리소스 ID
        resource_type: 리소스 유형 ('EC2' | 'RDS' | 'ELB' | 'TG')

    Returns:
        태그 딕셔너리 (키-값 쌍). API 오류 시 빈 딕셔너리 반환.
    """
    try:
        if resource_type == "EC2":
            return _get_ec2_tags(resource_id)
        elif resource_type == "RDS":
            return _get_rds_tags(resource_id)
        elif resource_type in ("ELB", "TG", "ALB", "NLB"):
            return _get_elbv2_tags(resource_id)
        else:
            logger.warning("Unsupported resource_type %r for resource %s", resource_type, resource_id)
            return {}
    except ClientError as e:
        logger.error(
            "AWS API error fetching tags for %s (%s): %s",
            resource_id, resource_type, e,
        )
        return {}
    except Exception as e:
        logger.error(
            "Unexpected error fetching tags for %s (%s): %s",
            resource_id, resource_type, e,
        )
        return {}


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2")


@functools.lru_cache(maxsize=None)
def _get_rds_client():
    return boto3.client("rds")


@functools.lru_cache(maxsize=None)
def _get_elbv2_client():
    return boto3.client("elbv2")


def _get_ec2_tags(instance_id: str) -> dict:
    """EC2 인스턴스 태그 조회"""
    ec2 = _get_ec2_client()
    response = ec2.describe_instances(InstanceIds=[instance_id])
    reservations = response.get("Reservations", [])
    if not reservations:
        return {}
    instances = reservations[0].get("Instances", [])
    if not instances:
        return {}
    raw_tags = instances[0].get("Tags", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}


def _get_rds_tags(db_instance_id: str) -> dict:
    """RDS DB 인스턴스 태그 조회"""
    rds = _get_rds_client()
    response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_id)
    db_instances = response.get("DBInstances", [])
    if not db_instances:
        return {}
    db_arn = db_instances[0].get("DBInstanceArn", "")
    if not db_arn:
        return {}
    tag_response = rds.list_tags_for_resource(ResourceName=db_arn)
    raw_tags = tag_response.get("TagList", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}


def _get_elbv2_tags(resource_arn: str) -> dict:
    """ALB / TargetGroup 태그 조회 (ELBv2 공통)"""
    elbv2 = _get_elbv2_client()
    response = elbv2.describe_tags(ResourceArns=[resource_arn])
    tag_descriptions = response.get("TagDescriptions", [])
    if not tag_descriptions:
        return {}
    raw_tags = tag_descriptions[0].get("Tags", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}
