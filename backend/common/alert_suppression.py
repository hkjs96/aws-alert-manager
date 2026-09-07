"""
알림 정제 판정 — 보낼 가치가 있는가 (docs/specs/alert-pipeline/ R3)

**순수 함수다.** 저장소도 타이머도 건드리지 않고, 필요한 상태를 인자로 받아 판정만 돌려준다.
실행 런타임(Step Functions / Lambda)이 바뀌어도 이 규칙은 그대로 쓴다.

세 가지 결과:
  NOTIFY   지금 보낸다
  SUPPRESS 보내지 않는다 (사유 기록 — R2-3)
  DEFER    유예 후 재평가한다 (auto-pause). 유예 중 해소되면 그때 SUPPRESS로 끝난다

평가 순서가 곧 정책이다:
  1. 면제(SEV-1) — 어떤 억제도 적용하지 않는다 (R3-8)
  2. 정비창 — 사람이 "지금은 알람 예상됨"이라 선언한 구간 (R3-6)
  3. flapping 격리 — 반복 토글로 격리된 알람 (R3-7)
  4. 중복 — 재알림 주기 안이면 보내지 않는다 (R3-1)
  5. auto-pause — 유예 후에도 살아 있으면 그때 보낸다 (R3-2)

**억제는 알람이 아니라 알림 쪽에 둔다**(design.md D4). 알람쪽(M-of-N)에서 참으면 조정할 때
알람 700개를 고쳐야 하고, 알림쪽에서 참으면 설정 한 줄이면 된다. 둘은 겹치지 않고 쌓인다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from common.alert_event import AlertEvent

NOTIFY = "notify"
SUPPRESS = "suppress"
DEFER = "defer"

# 억제 사유 — EventHistoryTable에 그대로 기록되고 리포트(R9-2)의 집계 축이 된다.
REASON_SILENCE = "silence"
REASON_FLAPPING = "flapping"
REASON_DEDUP = "dedup"
REASON_AUTO_PAUSE = "auto_pause"
REASON_CLEARED = "cleared"
REASON_NOT_ACTIONABLE = "not_actionable"

#: Alertmanager 기본값을 출발점으로 삼는다 (design.md D4).
DEFAULT_REPEAT_INTERVAL_SEC = 4 * 3600


@dataclass(frozen=True)
class Silence:
    """정비창 — 이 구간에 매칭되는 알림을 보내지 않는다."""

    starts_at: datetime
    ends_at: datetime
    customer_id: str = ""        # 빈 값 = 모든 고객사
    resource_type: str = ""      # 빈 값 = 모든 타입
    reason: str = ""

    def covers(self, ev: AlertEvent, now: datetime) -> bool:
        if not (self.starts_at <= now < self.ends_at):
            return False
        if self.customer_id and self.customer_id != ev.customer_id:
            return False
        if self.resource_type and self.resource_type != ev.resource_type:
            return False
        return True


@dataclass
class SuppressionPolicy:
    """정제 설정. DB에서 읽어 넣는다 — 알람을 수정하지 않고 바꿀 수 있어야 한다 (R3-9)."""

    #: severity → auto-pause 유예(초). **실측 전까지 비워둔다** — 값이 없으면 유예하지 않는다.
    #: Phase 0(`scripts/analyze_alarm_history.py`)의 "N분 유예 시 억제율" 표로 정한다.
    auto_pause_sec: dict[str, int] = field(default_factory=dict)

    #: 같은 알람을 다시 알리기까지의 최소 간격
    repeat_interval_sec: int = DEFAULT_REPEAT_INTERVAL_SEC

    #: 어떤 억제도 적용하지 않는 severity (R3-8)
    exempt_severities: tuple[str, ...] = ("SEV-1",)

    silences: tuple[Silence, ...] = ()

    #: flapping — 창(일) 안에 하루 평균 이 횟수 이상 ALARM 진입이면 격리한다 (R3-7).
    #: 창 1일·3회 = "오늘 세 번째 발화부터 격리". 실측 스크립트의 후보 기준(3회/일)과 같은 식.
    flapping_window_days: float = 1.0
    flapping_per_day: int = 3
    #: 격리 시간. 격리 중에도 에피소드는 기록되므로 만료 시 아직 flapping이면 다시 격리된다.
    flapping_quarantine_sec: int = 3600

    def pause_for(self, severity: str) -> int:
        return int(self.auto_pause_sec.get(severity, 0))


@dataclass(frozen=True)
class Decision:
    action: str                      # NOTIFY | SUPPRESS | DEFER
    reason: str = ""
    defer_seconds: int = 0           # DEFER일 때만 의미 있음

    @property
    def suppressed(self) -> bool:
        return self.action == SUPPRESS


def fingerprint(ev: AlertEvent) -> str:
    """중복 판정 키. 같은 알람의 같은 발화는 같은 지문을 갖는다.

    `series_id`(계정#리소스#메트릭)를 그대로 쓴다 — 알람 이름은 임계치가 바뀌면 달라지므로
    이름 기준으로 묶으면 임계치 조정이 곧 중복 판정 초기화가 된다.
    """
    return ev.series_id


def decide(
    ev: AlertEvent,
    *,
    policy: SuppressionPolicy,
    last_notified_at: datetime | None = None,
    is_flapping: bool = False,
    already_notified: bool = False,
    now: datetime | None = None,
) -> Decision:
    """이벤트 하나에 대한 정제 판정.

    Args:
        ev: 정규화된 이벤트
        policy: 정제 설정
        last_notified_at: 같은 지문으로 마지막으로 알린 시각 (없으면 처음)
        is_flapping: 이 알람이 flapping으로 격리된 상태인가
        already_notified: 이 발화에 대해 이미 알렸는가 — 해소 알림 발송 여부를 가른다
        now: 판정 기준 시각 (테스트 주입용)
    """
    now = now or datetime.now(timezone.utc)

    # 상태 변경이 아닌 이벤트(알람 생성/수정/삭제)는 알림 대상이 아니다.
    # 이력에는 남지만(감사 목적) 사람을 깨우지는 않는다.
    if ev.event_type != "state_change":
        return Decision(SUPPRESS, REASON_NOT_ACTIONABLE)

    # 해소 전이: 알린 적이 있으면 해소를 알리고, 없으면 조용히 끝낸다.
    # (유예 중 스스로 풀린 알람이 여기로 온다 — auto-pause의 실제 이득이 발생하는 지점)
    if ev.is_clearing:
        return Decision(NOTIFY, REASON_CLEARED) if already_notified \
            else Decision(SUPPRESS, REASON_CLEARED)

    if not ev.is_firing:
        return Decision(SUPPRESS, REASON_NOT_ACTIONABLE)

    # 1. 면제 — SEV-1은 어떤 억제도 거치지 않는다
    if ev.severity in policy.exempt_severities:
        return Decision(NOTIFY)

    # 2. 정비창
    for silence in policy.silences:
        if silence.covers(ev, now):
            return Decision(SUPPRESS, REASON_SILENCE)

    # 3. flapping 격리
    if is_flapping:
        return Decision(SUPPRESS, REASON_FLAPPING)

    # 4. 중복 — 재알림 주기 안이면 보내지 않는다
    if last_notified_at is not None:
        elapsed = (now - last_notified_at).total_seconds()
        if 0 <= elapsed < policy.repeat_interval_sec:
            return Decision(SUPPRESS, REASON_DEDUP)

    # 5. auto-pause — 유예가 설정돼 있으면 그만큼 기다렸다 재평가한다
    pause = policy.pause_for(ev.severity)
    if pause > 0:
        return Decision(DEFER, REASON_AUTO_PAUSE, defer_seconds=pause)

    return Decision(NOTIFY)


def is_flapping(episode_count: int, window_days: float, threshold_per_day: int = 3) -> bool:
    """관측 창의 발화 횟수로 flapping 여부를 판정한다 (R3-7).

    `scripts/analyze_alarm_history.py`의 판정 기준과 같은 식이라, 실측 리포트에서 뽑은
    flapping 후보가 런타임에서도 같게 판정된다.
    """
    if window_days <= 0:
        return False
    return (episode_count / window_days) >= threshold_per_day
