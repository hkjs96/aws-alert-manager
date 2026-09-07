"""
알림 상태 — 지문별 판정 재료 (docs/specs/alert-pipeline/ design.md D9, plan-state-grouping.md §A)

"마지막으로 알린 시각", "지금 에피소드가 열려 있나", "flapping 격리 중인가"는 **상태**다.
append-only 이력에서 스캔으로 복원하면 이력이 길수록 틀린다 — 억제 항목 20건 뒤에 dedup이
조용히 풀리던 버그(review-2026-09-07 B1)가 그것이다. 그래서 지문(fingerprint)별 항목 하나에
모아 두고 이벤트가 올 때마다 갱신한다. 이력 테이블은 감사·재현·학습 데이터로만 남는다.

**순수 함수다.** 저장소를 모른다. 인제스터·그룹 워커·테스트가 같은 함수를 쓴다.

**멱등이다.** EventBridge는 at-least-once라 같은 이벤트가 두 번 올 수 있다. 같은 이벤트를
두 번 적용해도 결과가 같아야 에피소드가 두 번 세어져 flapping 판정이 틀리는 일이 없다.
갱신은 이벤트 발생 시각을 키로 중복을 걸러 이를 보장한다 (`test_pbt_alert_state.py`가 고정).

항목 `fp#{fingerprint}`:
    last_notified_at     마지막으로 알린(알렸을) 발화 시각            → decide(last_notified_at=)
    episode_open         ALARM 진입 후 아직 해소 전인가
    episode_started_at
    episode_notified     현재 에피소드의 발화를 알렸는가               → decide(already_notified=)
    recent_episodes      ALARM 진입 시각 목록(창 안, 정렬, 상한)       → is_flapping()
    quarantined_until    flapping 격리 종료 시각
    version / ttl        저장소가 관리 (조건부 갱신, 30일 만료)

알려진 한계: 해소 이벤트가 발화보다 먼저 도착하면(EventBridge 순서 비보장, 드묾) 에피소드가
다음 해소까지 열린 채 남는다. 판정에 미치는 영향은 해소 알림 1건 — 그룹 워커(§B)가
`episode_started_at`이 오래된 에피소드를 닫힌 것으로 취급해 보정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from common.alert_event import STATE_CHANGE, AlertEvent
from common.alert_suppression import (
    NOTIFY,
    REASON_FLAPPING,
    Decision,
    SuppressionPolicy,
    is_flapping,
)

FP_PREFIX = "fp#"
GRP_PREFIX = "grp#"

#: 한 달 조용했던 알람의 상태는 없어도 된다 — 첫 발화처럼 다룬다.
STATE_TTL_DAYS = 30

#: 창 안에 이보다 많이 울렸다면 flapping 판정에 더 필요하지 않다.
MAX_RECENT_EPISODES = 30

#: 저장소가 관리하는 필드 — 상태 비교·갱신에서 제외한다.
_STORAGE_FIELDS = frozenset({"state_key", "version", "ttl"})


def fp_key(fingerprint: str) -> str:
    return FP_PREFIX + fingerprint


def group_key(ev: AlertEvent) -> str:
    """그룹 축 — 고객사 × 등급 (Alertmanager 기본 축; design.md U3에서 조정)."""
    return f"{ev.customer_id}#{ev.severity}"


def grp_key(group: str) -> str:
    return GRP_PREFIX + group


@dataclass(frozen=True)
class StateInputs:
    """`decide()`에 넣을 재료."""

    last_notified_at: datetime | None = None
    is_flapping: bool = False
    already_notified: bool = False


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _episodes_in_window(state: dict | None, ev: AlertEvent, *, now: datetime,
                        policy: SuppressionPolicy) -> list[str]:
    """창 안의 에피소드 시각 — 정렬·중복 없음·상한. **현재 발화도 포함**한다.

    포함하지 않으면 "N번째 발화"가 N-1로 세어져 격리가 한 박자 늦는다.
    """
    window_start = now - timedelta(days=policy.flapping_window_days)
    candidates = list((state or {}).get("recent_episodes") or [])
    if ev.is_firing and ev.occurred_at:
        candidates.append(ev.occurred_at)
    kept = {t for t in candidates if (d := _parse(t)) is not None and d >= window_start}
    return sorted(kept)[-MAX_RECENT_EPISODES:]


def inputs_from_state(state: dict | None, ev: AlertEvent, *, now: datetime,
                      policy: SuppressionPolicy) -> StateInputs:
    """저장된 상태 → `decide()` 재료. 상태가 없으면 첫 발화로 본다."""
    state = state or {}
    quarantined = _parse(state.get("quarantined_until"))
    flapping = quarantined is not None and now < quarantined
    if not flapping and ev.is_firing:
        count = len(_episodes_in_window(state, ev, now=now, policy=policy))
        flapping = is_flapping(count, policy.flapping_window_days, policy.flapping_per_day)
    return StateInputs(
        last_notified_at=_parse(state.get("last_notified_at")),
        is_flapping=flapping,
        # 해소 알림은 "열려 있는 에피소드를 알렸을 때"만 — 닫힌 뒤 중복 해소가 와도 다시 알리지 않는다
        already_notified=bool(state.get("episode_open")) and bool(state.get("episode_notified")),
    )


def apply_event(state: dict | None, ev: AlertEvent, decision: Decision, *, now: datetime,
                policy: SuppressionPolicy) -> dict:
    """이벤트와 그 판정을 상태에 반영한 **새** 상태. 입력을 바꾸지 않는다.

    상태 전이가 아닌 이벤트(알람 생성/수정/삭제)는 상태를 건드리지 않는다.
    """
    new = {k: v for k, v in (state or {}).items() if k not in _STORAGE_FIELDS}
    if ev.event_type != STATE_CHANGE:
        return new

    if ev.is_firing:
        new["recent_episodes"] = _episodes_in_window(state, ev, now=now, policy=policy)
        if not new.get("episode_open"):
            new["episode_open"] = True
            new["episode_started_at"] = ev.occurred_at
            new["episode_notified"] = False
        if decision.action == NOTIFY:
            new["last_notified_at"] = ev.occurred_at
            new["episode_notified"] = True
        if decision.reason == REASON_FLAPPING:
            # 새로 감지된 경우에만 격리 시작 — 이미 격리 중이면 종료 시각을 밀지 않는다
            q = _parse(new.get("quarantined_until"))
            if q is None or now >= q:
                new["quarantined_until"] = _iso(
                    now + timedelta(seconds=policy.flapping_quarantine_sec))
    elif ev.is_clearing:
        if new.get("episode_open"):
            new["episode_open"] = False
    return new


def unchanged(state: dict | None, new: dict) -> bool:
    """갱신할 게 없는가 — 그러면 쓰기를 건너뛴다(비용·경쟁 모두 줄어든다)."""
    return {k: v for k, v in (state or {}).items() if k not in _STORAGE_FIELDS} == new


def state_item(key: str, state: dict, *, now: datetime, version: int,
               ttl_days: int = STATE_TTL_DAYS) -> dict:
    """상태 → 테이블 항목. `version`은 저장소가 조건부 갱신에 쓴다."""
    item = {k: v for k, v in state.items() if k not in _STORAGE_FIELDS}
    item["state_key"] = key
    item["version"] = int(version)
    item["ttl"] = int((now + timedelta(days=ttl_days)).timestamp())
    return item
