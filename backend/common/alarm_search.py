"""
Alarm Search — 알람 검색/삭제 로직

CloudWatch 알람 검색과 삭제를 전담한다.
레거시 + 새 포맷 알람 검색, 배치 삭제, 배치 describe를 제공한다.
"""

import logging

from botocore.exceptions import ClientError

import common._clients as _clients
from common.alarm_naming import _shorten_elb_resource_id

logger = logging.getLogger("common.alarm_manager")

_ALL_TYPE_PREFIXES = tuple(
    f"[{rt}] " for rt in (
        "EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS", "DocDB", "ElastiCache",
        "NAT", "Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB",
        "OpenSearch", "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
        "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
    )
)


def _candidate_prefixes(resource_type: str) -> list[str]:
    """새 포맷 알람 검색에 쓸 이름 프리픽스 목록 (레거시 타입명 호환 포함).

    라이브 검색(_find_alarms_for_resource)과 인메모리 인덱스(AlarmIndex)가
    같은 매칭 규칙을 쓰도록 여기 한 곳에서 정의한다.
    """
    prefixes = (
        [f"[{resource_type}] "] if resource_type else list(_ALL_TYPE_PREFIXES)
    )
    # 레거시 [ELB] prefix 호환: ALB/NLB/TG는 기존 [ELB] 알람도 검색
    if resource_type in ("ALB", "NLB", "TG"):
        prefixes.append("[ELB] ")
    # 레거시 [NATGateway] prefix 호환: NAT 리네임 이전 알람 검색
    if resource_type == "NAT":
        prefixes.append("[NATGateway] ")
    return prefixes


def _match_suffixes(
    resource_id: str,
    resource_type: str,
    resource_tags: dict | None = None,
) -> set[str]:
    """리소스를 알람 이름과 매칭할 (TagName: ...) 서픽스 집합."""
    short_id = _shorten_elb_resource_id(resource_id, resource_type, resource_tags)
    suffixes = {f"(TagName: {short_id})"}
    if short_id != resource_id:
        suffixes.add(f"(TagName: {resource_id})")  # 레거시 Full_ARN 호환
    return suffixes


def _find_alarms_for_resource(
    resource_id: str,
    resource_type: str = "",
    *,
    resource_tags: dict | None = None,
    cw=None,
) -> list[str]:
    """resource_id에 해당하는 모든 알람 이름 조회 (새/레거시 포맷).

    검색 전략 (전체 풀스캔 금지 - 거버넌스 규칙 6):
    1) 레거시: AlarmNamePrefix=resource_id (레거시 알람 호환)
    2) 새 포맷: AlarmNamePrefix="[{resource_type}] " + suffix 필터
       resource_type 지정 시 해당 타입만, 미지정 시 전 타입 검색

    daily run처럼 리소스를 대량 순회하는 경로에서는 이 함수 대신
    `common.alarm_index.AlarmIndex`(런당 1회 전체 조회 + 인메모리 매칭)를
    사용한다 — 타입 프리픽스 스캔은 리소스 수 × 타입 알람 수에 비례해
    API 콜을 만든다.
    """
    cw = cw or _clients._get_cw_client()
    seen: set[str] = set()
    alarm_names: list[str] = []
    suffixes = _match_suffixes(resource_id, resource_type, resource_tags)

    def _collect(prefix: str, filter_suffix: bool = False) -> None:
        try:
            paginator = cw.get_paginator("describe_alarms")
            for page in paginator.paginate(AlarmNamePrefix=prefix):
                for a in page.get("MetricAlarms", []):
                    name = a["AlarmName"]
                    if filter_suffix and not any(name.endswith(s) for s in suffixes):
                        continue
                    if name not in seen:
                        seen.add(name)
                        alarm_names.append(name)
        except ClientError as e:
            logger.error(
                "Failed to list alarms prefix=%s for %s: %s",
                prefix, resource_id, e,
            )

    # 1) 레거시 prefix 검색
    _collect(resource_id)

    # 2) 새 포맷: resource_type prefix 기반 검색 + suffix 필터
    for p in _candidate_prefixes(resource_type):
        _collect(p, filter_suffix=True)

    return alarm_names


def _delete_all_alarms_for_resource(
    resource_id: str,
    resource_type: str = "",
    *,
    cw=None,
) -> list[str]:
    """리소스의 모든 알람 삭제 (레거시 + 새 포맷). 내부용."""
    cw = cw or _clients._get_cw_client()
    alarm_names = _find_alarms_for_resource(resource_id, resource_type, cw=cw)
    if not alarm_names:
        return []
    deleted = []
    try:
        # CloudWatch delete_alarms 최대 100개씩
        for i in range(0, len(alarm_names), 100):
            cw.delete_alarms(AlarmNames=alarm_names[i:i+100])
        logger.info("Deleted alarms: %s", alarm_names)
        deleted = alarm_names
    except ClientError as e:
        logger.error("Failed to delete alarms for %s: %s", resource_id, e)
    return deleted


def _describe_alarms_batch(alarm_names: list[str], *, cw=None) -> dict[str, dict]:
    """알람 이름 목록으로 describe_alarms 1회 호출 (100개씩 배치)."""
    cw = cw or _clients._get_cw_client()
    alarm_map: dict[str, dict] = {}
    for i in range(0, len(alarm_names), 100):
        batch = alarm_names[i:i + 100]
        try:
            resp = cw.describe_alarms(AlarmNames=batch)
            for a in resp.get("MetricAlarms", []):
                alarm_map[a["AlarmName"]] = a
        except ClientError as e:
            logger.error("Failed to describe alarms batch: %s", e)
    return alarm_map


def _delete_alarm_names(cw, alarm_names: list[str]) -> None:
    """알람 이름 목록으로 삭제 (에러 로깅)."""
    try:
        cw.delete_alarms(AlarmNames=alarm_names)
    except ClientError as e:
        logger.error("Failed to delete alarms %s: %s", alarm_names, e)
