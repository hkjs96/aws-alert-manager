"""
Collector 공통 인터페이스 및 유틸리티 — Requirements 1.10, 1.11, 2.10, 2.11

CollectorProtocol: 모든 Collector가 구현해야 하는 인터페이스 (코딩 거버넌스 §5)
query_metric(): CloudWatch get_metric_statistics 공통 래퍼 (코딩 거버넌스 §10)
collect_metric(): 메트릭 조회 + metrics_dict 저장 + 로그 공통 헬퍼 (코딩 거버넌스 §10)
_get_cw_client(): lru_cache 기반 CloudWatch 클라이언트 싱글턴 (코딩 거버넌스 §1)
"""

import functools
import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo

logger = logging.getLogger(__name__)

# CloudWatch 메트릭 조회 기본값
CW_PERIOD = 300
CW_STAT_AVG = "Average"
CW_STAT_SUM = "Sum"
CW_STAT_MIN = "Minimum"
CW_LOOKBACK_MINUTES = 10

# GetMetricData 한 요청에 담을 수 있는 쿼리 수
_MAX_METRIC_DATA_QUERIES = 500


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

    def resolve_alive_ids(self, tag_names: set[str]) -> set[str]:
        """알람 TagName 집합에서 실제 AWS 리소스가 존재하는 TagName 부분집합 반환."""
        ...


# ──────────────────────────────────────────────
# 런 스코프 메트릭 배치 (record → execute → serve)
# ──────────────────────────────────────────────
# daily run은 리소스×메트릭당 get_metric_statistics 1콜을 만든다(리소스 200개
# 기준 ~600콜). GetMetricData는 한 요청에 500쿼리를 담을 수 있으므로,
# 컬렉터 인터페이스를 바꾸지 않고 query_metric 관문에서 배치한다:
#
#   1. record: get_metrics를 한 번 돌려 쿼리만 수집 (API 콜 없음, 반환값 None)
#   2. execute: 수집된 쿼리를 GetMetricData 500개/콜로 일괄 실행 → 캐시
#   3. serve: get_metrics 본 실행 — query_metric이 캐시에서 응답
#
# record 단계에서 등록되지 않은 쿼리(조건 분기 차이 등)는 serve 단계에서
# 기존 라이브 경로로 폴백하므로 정확성은 배치 여부와 무관하게 유지된다.

class MetricBatch:
    """query_metric 호출을 GetMetricData로 일괄 처리하는 런 스코프 배치."""

    def __init__(self):
        self._mode: str | None = None
        self._pending: dict[tuple, dict] = {}
        self._cache: dict[tuple, float | None] = {}

    @property
    def mode(self) -> str | None:
        return self._mode

    def record(self) -> None:
        self._mode = "record"

    def serve(self) -> None:
        self._mode = "serve"

    @staticmethod
    def key_for(namespace: str, metric_name: str, dimensions: list[dict], stat: str) -> tuple:
        dim_key = tuple(sorted((d.get("Name", ""), d.get("Value", "")) for d in dimensions))
        return (namespace, metric_name, dim_key, stat)

    def register(self, namespace: str, metric_name: str, dimensions: list[dict], stat: str) -> None:
        key = self.key_for(namespace, metric_name, dimensions, stat)
        self._pending.setdefault(key, {
            "namespace": namespace,
            "metric_name": metric_name,
            "dimensions": dimensions,
            "stat": stat,
        })

    def lookup(self, key: tuple) -> tuple[bool, float | None]:
        if key in self._cache:
            return True, self._cache[key]
        return False, None

    def execute(self, *, cw=None, lookback_minutes: int = CW_LOOKBACK_MINUTES) -> int:
        """수집된 쿼리를 GetMetricData로 일괄 실행. 실행한 API 콜 수 반환.

        실패한 청크의 키는 캐시에 남지 않으므로 serve 단계에서 자동으로
        라이브 경로 폴백된다 (부분 실패가 전체를 무너뜨리지 않는다).
        """
        if not self._pending:
            return 0
        cw = cw or _get_cw_client()
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_minutes)

        items = list(self._pending.items())
        calls = 0
        for i in range(0, len(items), _MAX_METRIC_DATA_QUERIES):
            chunk = items[i:i + _MAX_METRIC_DATA_QUERIES]
            id_map: dict[str, tuple] = {}
            queries = []
            for j, (key, spec) in enumerate(chunk):
                qid = f"q{i + j}"
                id_map[qid] = key
                queries.append({
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": spec["namespace"],
                            "MetricName": spec["metric_name"],
                            "Dimensions": spec["dimensions"],
                        },
                        "Period": CW_PERIOD,
                        "Stat": spec["stat"],
                    },
                    "ReturnData": True,
                })

            kwargs = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime": end,
                # 내림차순 → Values[0]이 최신 데이터포인트 (라이브 경로와 동일 의미)
                "ScanBy": "TimestampDescending",
            }
            while True:
                try:
                    resp = cw.get_metric_data(**kwargs)
                except ClientError as e:
                    logger.error("Metric batch get_metric_data failed (chunk %d): %s", i, e)
                    break
                calls += 1
                for result in resp.get("MetricDataResults", []):
                    key = id_map.get(result.get("Id", ""))
                    if key is None:
                        continue
                    values = result.get("Values", [])
                    if key not in self._cache:
                        self._cache[key] = values[0] if values else None
                    elif self._cache[key] is None and values:
                        # 앞 페이지에 값이 없던 시리즈 — 이 페이지의 첫 값이 최신
                        self._cache[key] = values[0]
                token = resp.get("NextToken")
                if not token:
                    break
                kwargs["NextToken"] = token

        logger.info(
            "Metric batch executed: %d queries in %d GetMetricData calls",
            len(items), calls,
        )
        return calls


_active_metric_batch: MetricBatch | None = None


def set_active_metric_batch(batch: MetricBatch | None) -> None:
    """런 스코프 배치를 활성화/해제한다 (daily runner 전용)."""
    global _active_metric_batch
    _active_metric_batch = batch


def _recording_active() -> bool:
    return _active_metric_batch is not None and _active_metric_batch.mode == "record"


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
    batch = _active_metric_batch
    if batch is not None:
        key = MetricBatch.key_for(namespace, metric_name, dimensions, stat)
        if batch.mode == "record":
            batch.register(namespace, metric_name, dimensions, stat)
            return None
        if batch.mode == "serve":
            found, value = batch.lookup(key)
            if found:
                return value
            # record 단계에서 등록되지 않았거나 실행이 실패한 쿼리 — 라이브 폴백

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


def collect_metric(
    namespace: str,
    cw_metric_name: str,
    dimensions: list[dict],
    start_time: datetime,
    end_time: datetime,
    result_key: str,
    metrics_dict: dict,
    *,
    stat: str = CW_STAT_AVG,
    transform=None,
    resource_label: str = "resource",
) -> None:
    """
    단일 메트릭 조회 후 metrics_dict에 저장하는 공통 헬퍼 (코딩 거버넌스 §10).

    25개 Collector의 로컬 _collect_metric() 함수를 단일 구현으로 통합한다.
    CloudFront처럼 별도 CW 클라이언트가 필요한 경우에는 이 함수를 사용하지 않는다.

    Args:
        namespace: CloudWatch 네임스페이스 (예: "AWS/EC2", "CWAgent")
        cw_metric_name: CloudWatch 메트릭 이름 (예: "CPUUtilization")
        dimensions: CloudWatch 디멘션 리스트
        start_time: 조회 시작 시간 (UTC)
        end_time: 조회 종료 시간 (UTC)
        result_key: metrics_dict에 저장할 키 이름 (예: "CPU", "FreeMemoryGB")
        metrics_dict: 결과를 저장할 딕셔너리 (in-place 수정)
        stat: CloudWatch 통계 유형. 기본값 "Average".
        transform: 값 변환 함수 (예: bytes → GB 변환). None이면 변환 없음.
        resource_label: 로그 메시지에 표시할 리소스 유형 이름 (예: "EC2", "RDS").
    """
    resource_id = dimensions[0]["Value"] if dimensions else "unknown"
    value = query_metric(namespace, cw_metric_name, dimensions, start_time, end_time, stat)
    if value is not None:
        metrics_dict[result_key] = transform(value) if transform else value
    elif not _recording_active():
        # record 단계의 None은 "데이터 없음"이 아니라 "아직 조회 전"이므로 로그 생략
        logger.info(
            "Skipping %s metric for %s %s: no data",
            result_key, resource_label, resource_id,
        )
