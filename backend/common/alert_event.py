"""
알림 파이프라인 이벤트 스키마 — 클라우드 중립 정규화 (docs/specs/alert-pipeline/ R1-6, R2)

EventBridge로 들어온 CloudWatch 알람 이벤트를 이 모듈이 공통 형태로 바꾼다.
Azure/GCP 어댑터를 붙일 때 이 스키마는 그대로 두고 파서만 추가하면 되도록 설계한다.

**절대 예외를 던지지 않는다.** 파싱 실패는 곧 이벤트 유실이고, 유실된 이벤트는 되돌릴 수 없다
(R2-1: 정제 이전 원본 전량 기록). 알 수 없는 형태는 빈 필드 + `raw` 원본으로 남긴다.

키 설계:
- `series_id = "{account_id}#{resource_id}#{metric_key}"` — **MetricHistoryTable과 동일 규약.**
  같은 키로 "이 알람이 최근 몇 번 울렸나"(이 테이블)와 "평소 이 메트릭 값은"(메트릭 이력)을
  조인할 수 있다. Phase 4a 분석이 이 성질에 의존한다.
- `event_key = "{ISO8601}#{event_id 앞 8자}"` — 시간순 정렬 + 동일 시각 충돌 방지.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from common.alarm_identity import identify_alarm

logger = logging.getLogger(__name__)

#: 이벤트 이력 보관 기간. Phase 4 AIOps 학습에 3개월치가 필요하다(design.md D5).
RETENTION_DAYS = 90

#: EventBridge detail-type → 우리 이벤트 종류
STATE_CHANGE = "state_change"
CONFIG_CHANGE = "config_change"
UNKNOWN = "unknown"

_DETAIL_TYPE_MAP = {
    "CloudWatch Alarm State Change": STATE_CHANGE,
    "CloudWatch Alarm Configuration Change": CONFIG_CHANGE,
}


@dataclass
class AlertEvent:
    """정규화된 알림 이벤트. 클라우드 프로바이더에 중립적이다."""

    event_id: str = ""
    event_type: str = UNKNOWN          # state_change | config_change | unknown
    occurred_at: str = ""              # ISO8601 UTC
    provider: str = "aws"

    account_id: str = ""
    customer_id: str = ""              # 이벤트에 없다 — 호출자가 계정 매핑으로 채운다
    region: str = ""

    alarm_name: str = ""
    alarm_arn: str = ""
    resource_id: str = ""
    resource_type: str = ""
    metric_key: str = ""
    severity: str = ""

    state: str = ""                    # ALARM | OK | INSUFFICIENT_DATA
    previous_state: str = ""
    state_reason: str = ""
    operation: str = ""                # config_change일 때 create/update/delete

    #: 정제 결과 — 억제되었으면 사유를 남긴다 (R2-3)
    suppressed: bool = False
    suppression_reason: str = ""
    incident_id: str = ""

    raw: dict = field(default_factory=dict)
    parse_error: str = ""

    @property
    def series_id(self) -> str:
        """MetricHistoryTable과 동일한 시계열 키. 셋 중 하나라도 비면 조인이 안 되므로 그대로 둔다."""
        return f"{self.account_id}#{self.resource_id}#{self.metric_key}"

    @property
    def event_key(self) -> str:
        """정렬 키. 같은 시각에 여러 건이 와도 충돌하지 않게 event_id 일부를 붙인다."""
        return f"{self.occurred_at}#{self.event_id[:8]}"

    @property
    def is_firing(self) -> bool:
        return self.state == "ALARM"

    @property
    def is_clearing(self) -> bool:
        """ALARM에서 벗어난 전이인가 — auto-pause 취소 판단에 쓴다."""
        return self.previous_state == "ALARM" and self.state in ("OK", "INSUFFICIENT_DATA")


def _metric_key_from_configuration(detail: dict) -> str:
    """configuration.metrics[].metricStat.metric.name — 메타데이터가 없을 때의 폴백."""
    for m in (detail.get("configuration") or {}).get("metrics") or []:
        name = ((m.get("metricStat") or {}).get("metric") or {}).get("name")
        if name:
            return str(name)
    return ""


def from_eventbridge(event: dict, *, customer_id: str = "") -> AlertEvent:
    """EventBridge CloudWatch 알람 이벤트 → AlertEvent.

    어떤 입력이 와도 예외를 던지지 않는다. 해석 실패 시 `parse_error`에 사유를 남기고
    `raw`에 원본을 보존해, 나중에 파서를 고쳐 소급 재처리할 수 있게 한다(R2-5).
    """
    ev = AlertEvent(raw=event if isinstance(event, dict) else {"_unparseable": str(event)})
    if not isinstance(event, dict):
        ev.parse_error = "event is not a dict"
        return ev

    try:
        ev.event_id = str(event.get("id", ""))
        ev.occurred_at = str(event.get("time", ""))
        ev.account_id = str(event.get("account", ""))
        ev.region = str(event.get("region", ""))
        ev.customer_id = customer_id
        ev.event_type = _DETAIL_TYPE_MAP.get(str(event.get("detail-type", "")), UNKNOWN)

        resources = event.get("resources") or []
        ev.alarm_arn = str(resources[0]) if resources else ""

        detail = event.get("detail") or {}
        ev.alarm_name = str(detail.get("alarmName", ""))
        ev.operation = str(detail.get("operation", ""))
        ev.state = str((detail.get("state") or {}).get("value", ""))
        ev.previous_state = str((detail.get("previousState") or {}).get("value", ""))
        ev.state_reason = str((detail.get("state") or {}).get("reason", ""))[:500]

        # 리소스 해석은 기존 모듈에 위임 — AlarmDescription 메타데이터 우선, 이름 폴백.
        # description은 configuration에 실려 오며, 없으면 이름만으로 해석된다.
        description = str((detail.get("configuration") or {}).get("description", ""))
        identity = identify_alarm({
            "AlarmName": ev.alarm_name, "AlarmDescription": description,
        })
        if identity is not None:
            ev.resource_id = identity.resource_id
            ev.resource_type = identity.resource_type
            ev.metric_key = identity.metric_key or _metric_key_from_configuration(detail)
        else:
            # 우리가 관리하지 않는 알람(고객사 자체 알람, 인프라 알람 등)도 버리지 않는다 —
            # 억제·라우팅 대상은 아니지만 이력으로는 남긴다.
            ev.metric_key = _metric_key_from_configuration(detail)
            ev.parse_error = "unmanaged alarm format"
    except (AttributeError, TypeError, ValueError, IndexError) as e:
        ev.parse_error = f"{type(e).__name__}: {e}"
        logger.warning("Alert event parse degraded (%s): %s", ev.parse_error, ev.event_id)

    return ev


def to_item(ev: AlertEvent, *, now: datetime | None = None,
            retention_days: int = RETENTION_DAYS) -> dict:
    """AlertEvent → EventHistoryTable 항목.

    빈 문자열 필드는 DynamoDB에 넣지 않는다(항목 크기·비용). 단 키(series_id/event_key)와
    억제 플래그는 항상 넣는다 — 쿼리와 집계가 이들의 존재를 전제한다.
    """
    now = now or datetime.now(timezone.utc)
    item: dict = {
        "series_id": ev.series_id,
        "event_key": ev.event_key,
        "event_id": ev.event_id,
        "event_type": ev.event_type,
        "suppressed": ev.suppressed,
        "ttl": int((now + timedelta(days=retention_days)).timestamp()),
    }
    # GSI 파티션: 고객사·일자. 리포트(R9)와 기간 조회용.
    day = ev.occurred_at[:10] or now.date().isoformat()
    item["customer_day"] = f"{ev.customer_id}#{day}"

    for key, value in (
        ("occurred_at", ev.occurred_at), ("account_id", ev.account_id),
        ("customer_id", ev.customer_id), ("region", ev.region),
        ("alarm_name", ev.alarm_name), ("alarm_arn", ev.alarm_arn),
        ("resource_id", ev.resource_id), ("resource_type", ev.resource_type),
        ("metric_key", ev.metric_key), ("severity", ev.severity),
        ("state", ev.state), ("previous_state", ev.previous_state),
        ("state_reason", ev.state_reason), ("operation", ev.operation),
        ("suppression_reason", ev.suppression_reason), ("incident_id", ev.incident_id),
        ("parse_error", ev.parse_error), ("provider", ev.provider),
    ):
        if value:
            item[key] = value

    # 원본 보존 — 정제 규칙을 바꾼 뒤 과거 판단을 소급 검증하려면 필요하다(R2-5).
    # DynamoDB는 float를 거부하므로 JSON 문자열로 넣는다.
    if ev.raw:
        try:
            item["raw"] = json.dumps(ev.raw, ensure_ascii=False, separators=(",", ":"))[:8000]
        except (TypeError, ValueError):
            item["raw"] = str(ev.raw)[:8000]
    return item
