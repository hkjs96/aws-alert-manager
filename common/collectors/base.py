"""
Collector 공통 인터페이스 및 유틸리티 — Requirements 1.10, 1.11, 2.10, 2.11

CollectorProtocol: 모든 Collector가 구현해야 하는 인터페이스 (코딩 거버넌스 §5)
query_metric(): CloudWatch get_metric_statistics 공통 래퍼 (코딩 거버넌스 §10)
_get_cw_client(): lru_cache 기반 CloudWatch 클라이언트 싱글턴 (코딩 거버넌스 §1)
"""

import functools
import logging
from datetime import datetime
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo

logger = logging.getLogger(__name__)

# CloudWatch 메트릭 조회 기본값
CW_PERIOD = 300
CW_STAT_AVG = "Average"
CW_STAT_SUM = "Sum"
CW_LOOKBACK_MINUTES = 10


# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_cw_client():
    """CloudWatch 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("cloudwatch")


# ──────────────────────────────────────────────
# Collector 인터페이스 (코딩 거버넌스 §5)
# ──────────────────────────────────────────────

class CollectorProtocol(Protocol):
    """모든 Collector 모듈이 구현해야 하는 인터페이스."""

    def collect_monitored_resources(self) -> list[ResourceInfo]:
        """Monitoring=on 태그가 있는 리소스 목록 반환."""
        ...

    def get_metrics(
        self, resource_id: str, resource_tags: dict
    ) -> dict[str, float] | None:
        """CloudWatch에서 리소스 메트릭 조회. 데이터 없으면 None."""
        ...


# ──────────────────────────────────────────────
# CloudWatch 메트릭 조회 공통 유틸리티 (코딩 거버넌스 §10)
# ──────────────────────────────────────────────

def query_metric(
    namespace: str,
    metric_name: str,
    dimensions: list[dict],
    start_time: datetime,
    end_time: datetime,
    stat: str = CW_STAT_AVG,
) -> float | None:
    """
    CloudWatch get_metric_statistics 공통 래퍼.

    기존 ec2/rds/elb의 _query_metric()을 통합한 유틸리티.
    가장 최근 데이터포인트의 값을 반환하며, 데이터 없으면 None.

    Args:
        namespace: CloudWatch 네임스페이스 (예: "AWS/EC2", "CWAgent")
        metric_name: 메트릭 이름 (예: "CPUUtilization")
        dimensions: CloudWatch 디멘션 리스트
        start_time: 조회 시작 시간 (UTC)
        end_time: 조회 종료 시간 (UTC)
        stat: 통계 유형 ("Average" | "Sum"). 기본값 "Average".

    Returns:
        최근 데이터포인트 값 또는 None (데이터 없음/오류 시)
    """
    try:
        cw = _get_cw_client()
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=CW_PERIOD,
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
