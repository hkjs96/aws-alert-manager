"""
알림 그룹 — 그룹 단위 타이머의 순수 부분 (design.md D10, plan-state-grouping.md §B)

이벤트마다 Step Functions 실행을 만들면 폭풍 한 번에 실행 2만 개가 생기고, 유예가 끝나면
2만 개가 각자 알림을 보낸다. 실행은 **그룹당 하나**다: 첫 이벤트가 그룹을 열고 실행을 시작하며,
후속 이벤트는 이력 항목에 `group_id`만 적는다. 실행이 깨어날 때 그 `group_id`로 구성원을 읽는다.

**구성원 자격은 인제스터가 적재 시점에 정한다**(이력 항목의 `group_id`). 시간 창으로 구성원을
정하면 "닫힌 직후 도착한 늦은 이벤트"가 어느 창에도 안 잡히거나 두 창에 잡힌다 — ID로 정하면
정확히 한 그룹에 속한다.

실행 이름 = 그룹 ID. **결정적**이라(그룹 키 해시 + 연 시각) 그룹을 연 쪽이 StartExecution 전에
죽어도 다음 이벤트가 같은 이름으로 다시 시작할 수 있고, Step Functions가 중복을 멱등 처리한다.
"""

from __future__ import annotations

import hashlib
import re

from common.alert_event import STATE_CHANGE, AlertEvent
from common.alert_suppression import DEFER, NOTIFY, Decision

#: grp# 항목 수명 — 하루 지난 그룹 상태는 의미가 없다.
GROUP_TTL_DAYS = 1

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

#: 실행 이름 제약: ≤80자, 공백·`#`·`:`·`/` 등 금지. 그룹 키는 `#`를 포함하므로 해시한다.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def should_group(ev: AlertEvent, decision: Decision) -> bool:
    """그룹에 넣을 이벤트인가 — 보낼(NOTIFY) 또는 보낼지 유예 중인(DEFER) 상태 전이만.

    억제된 이벤트로 그룹을 열면 폭풍의 억제 이벤트 수만큼 실행이 생긴다.
    """
    return ev.event_type == STATE_CHANGE and decision.action in (NOTIFY, DEFER)


def execution_name(group_key: str, opened_at: str) -> str:
    """Step Functions 실행 이름이자 그룹 ID. 같은 (그룹 키, 연 시각)이면 같은 이름."""
    digest = hashlib.sha1(group_key.encode("utf-8")).hexdigest()[:16]
    stamp = re.sub(r"\D", "", opened_at)[:14] or "0"
    name = f"g-{digest}-{stamp}"
    assert _NAME_RE.match(name), name
    return name


def execution_arn(state_machine_arn: str, name: str) -> str:
    """실행 ARN은 상태 머신 ARN과 이름으로 결정된다 — ExecutionAlreadyExists 때 조회 없이 만든다."""
    return state_machine_arn.replace(":stateMachine:", ":execution:", 1) + ":" + name


def new_group(group_key: str, ev: AlertEvent, *, opened_at: str, group_wait_sec: int) -> dict:
    """grp# 항목(저장 필드 제외). 실행 입력에 필요한 것을 함께 담아 둔다."""
    return {
        "status": STATUS_OPEN,
        "group_id": execution_name(group_key, opened_at),
        "group_key": group_key,
        "customer_id": ev.customer_id,
        "severity": ev.severity,
        "opened_at": opened_at,
        "group_wait_sec": int(group_wait_sec),
    }


def execution_input(group: dict) -> dict:
    """상태 머신 입력. 워커는 이걸로 grp#/이력을 다시 읽는다 — 큰 페이로드를 실행에 싣지 않는다."""
    return {
        "group_id": str(group.get("group_id", "")),
        "group_key": str(group.get("group_key", "")),
        "customer_id": str(group.get("customer_id", "")),
        "severity": str(group.get("severity", "")),
        "opened_at": str(group.get("opened_at", "")),
        "group_wait_sec": int(group.get("group_wait_sec", 30)),
    }
