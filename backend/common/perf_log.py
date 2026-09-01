"""
구조화 성능 로그 — CloudWatch Logs Insights로 집계한다.

왜 커스텀 메트릭(EMF)이 아니라 로그인가: CloudWatch 커스텀 메트릭은 **메트릭당 $0.30/월**이라
라우트 29개 × 통계 조합이면 금방 수십 달러가 된다. 같은 질문("어느 라우트가 느린가, p95는")에
Logs Insights가 답할 수 있고, 로그 수집은 무료 구간(5GB/월) 안이라 사실상 $0다.
(비용 근거: docs/reports/COST-IMPACT-2026-08-31.md §1)

포맷: 한 줄에 마커 + JSON. Lambda 로그 포맷(TEXT/JSON)이 무엇이든 Insights의 정규식 `parse`로
읽을 수 있게 마커를 앞에 둔다 — JSON 자동 필드 발견에 의존하면 로그 포맷 설정에 묶인다.

    PERF_METRIC {"metric":"api_request","route":"GET /resources","duration_ms":123.4,...}

쿼리 모음: docs/OBSERVABILITY.md
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

#: Insights 쿼리가 잡는 고정 마커. 바꾸면 docs/OBSERVABILITY.md의 쿼리도 함께 고쳐야 한다.
PERF_MARKER = "PERF_METRIC"


def log_perf(metric: str, duration_ms: float, **fields) -> None:
    """성능 측정 1건을 구조화 로그로 남긴다.

    Args:
        metric: 측정 종류 (예: "api_request", "daily_stage").
        duration_ms: 소요 시간(ms).
        **fields: 집계 축으로 쓸 추가 필드 (route, status, cold 등).
                  값은 JSON 직렬화 가능해야 하며, 직렬화 불가 값은 str()로 강등된다.

    측정 자체가 요청을 실패시키면 안 되므로 예외를 삼킨다.
    """
    # separators를 compact로 고정한다: Insights 쿼리가 `"route":"..."` 형태로 값을 뽑는데
    # json.dumps 기본값(", ", ": ")은 `"route": "..."`를 만들어 정규식이 빗나간다.
    # 로그 용량도 줄어 수집 비용에 유리하다.
    payload = {"metric": metric, "duration_ms": round(float(duration_ms), 2), **fields}
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        body = json.dumps(
            {"metric": metric, "duration_ms": round(float(duration_ms), 2)},
            separators=(",", ":"),
        )
    logger.info("%s %s", PERF_MARKER, body)


class Timer:
    """with 블록의 소요 시간을 재서 log_perf로 남긴다.

    예외가 나도 시간을 남기고 예외는 그대로 전파한다 — 느린 실패도 측정 대상이다.

        with Timer("daily_stage", stage="inventory_sync"):
            _sync_inventory(...)
    """

    def __init__(self, metric: str, **fields):
        self._metric = metric
        self._fields = fields
        self._start = 0.0

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000

    def set(self, **fields) -> None:
        """블록 안에서 알게 된 값(건수 등)을 측정에 얹는다."""
        self._fields.update(fields)

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._fields.setdefault("ok", exc_type is None)
        log_perf(self._metric, self.elapsed_ms, **self._fields)
        return False
