"""
알림 처리 판정의 **최종값**과 그 사람 설명 (review-personas F7)

이력 한 줄만 봐서는 "이 알람이 나갔는지"를 알 수 없다. 적재 시점 판정(`suppressed`/
`suppression_reason`)과 그룹 실행이 나중에 확정한 값(`final_action`/`final_reason`)이 따로 있고,
유예(auto_pause) 중인 것은 아직 결정되지 않았다. 이 모듈이 그 규칙 하나를 갖는다 —
억제율 리포트(`scripts/alert_suppression_report.py`)와 조회 API가 같은 답을 내야 하기 때문이다.

**사유 문구도 여기 있다.** 고객이 보는 것은 `dedup` 같은 내부 토큰이 아니라 "왜 안 왔는지"다.
프런트가 각자 번역하면 화면마다 말이 갈리므로 백엔드가 정본을 준다.
"""

from __future__ import annotations

NOTIFY, SUPPRESS, PENDING = "notify", "suppress", "pending"

#: 해소로 치는 상태 — ALARM에서 여기로 오면 "풀렸다"
_CLEAR_STATES = ("OK", "INSUFFICIENT_DATA")

#: 그룹 워커가 죽은 실행을 대신 확정할 때 사유 앞에 붙이는 표식 (review-personas F4)
SWEPT_PREFIX = "swept:"


def effective(item: dict) -> tuple[str, str]:
    """이력 항목의 최종 판정 (action, reason).

    순서가 곧 규칙이다:
      1. `final_action` 있음    → 그것. 그룹 실행이 확정한 값이 적재 시점 판정을 이긴다
      2. `suppressed=True`      → suppress. 적재 시 억제
      3. reason=auto_pause      → pending. 유예 중이라 아직 확정 전 (실행이 끝나면 1로 바뀐다)
      4. 그 외                  → notify
    """
    final = item.get("final_action")
    if final:
        return str(final), str(item.get("final_reason", "") or "")
    reason = str(item.get("suppression_reason", "") or "")
    if item.get("suppressed"):
        return SUPPRESS, reason
    if reason == "auto_pause":
        return PENDING, reason
    return NOTIFY, reason


def kind(item: dict) -> str:
    """firing | clearing | other | config"""
    if item.get("event_type") != "state_change":
        return "config"
    if item.get("state") == "ALARM":
        return "firing"
    if item.get("previous_state") == "ALARM" and item.get("state") in _CLEAR_STATES:
        return "clearing"
    return "other"


# ──────────────────────────────────────────────
# 사람 설명 — 화면에 그대로 나가는 문구
# ──────────────────────────────────────────────

#: reason 토큰 → (짧은 라벨, 설명). 설명은 "왜 이 알림이 안 갔는가"에 답해야 한다.
_REASONS: dict[str, tuple[str, str]] = {
    "dedup": ("중복 병합",
              "같은 알람을 최근에 이미 알렸습니다. 재발화 병합 창 안이라 한 건으로 합쳤습니다."),
    "flapping": ("진동 격리",
                 "짧은 시간에 발화와 해소를 반복해 격리했습니다. 격리가 끝나면 다시 알립니다."),
    "silence": ("정비창",
                "이 시간대에 등록된 정비창이 있어 알리지 않았습니다."),
    "cleared": ("해소",
                "알람이 정상으로 돌아왔습니다. 발화를 알린 적이 있을 때만 해소도 알립니다."),
    "not_actionable": ("대상 아님",
                       "상태 전이가 아닌 이벤트입니다(알람 생성·수정·삭제 등). 기록만 합니다."),
    "auto_pause": ("자동 유예",
                   "바로 알리지 않고 잠시 기다립니다. 그 사이 스스로 풀리면 알리지 않습니다."),
    "auto_pause_expired": ("유예 후 발송",
                           "유예 시간이 지나도 계속 울리고 있어 알렸습니다."),
    "state_contention": ("상태 경합",
                         "같은 알람이 동시에 처리돼 판정을 확정하지 못했습니다. 놓치지 않도록 알렸습니다."),
    "": ("정상 발송", "억제 규칙에 걸리지 않아 알렸습니다."),
}

#: action → 짧은 라벨. 이력 화면의 뱃지 텍스트.
_ACTIONS: dict[str, str] = {
    NOTIFY: "발송",
    SUPPRESS: "억제",
    PENDING: "유예 중",
}

_SWEPT = ("실행 실패 후 발송",
          "알림 묶음을 처리하던 실행이 실패해, 놓치지 않도록 대신 확정해 알렸습니다.")


def describe(action: str, reason: str) -> dict[str, str]:
    """(판정, 사유) → 화면에 그대로 쓸 문구.

    모르는 사유도 삼키지 않는다 — 토큰을 그대로 라벨로 보여준다. 조용히 "정상"으로
    바꾸면 새 억제 규칙이 생겼을 때 고객이 이유를 못 보게 된다.
    """
    action = str(action or "")
    reason = str(reason or "")

    # 죽은 실행 청소는 `auto_pause_expired;swept:failed`처럼 원래 사유 뒤에 붙는다
    swept = SWEPT_PREFIX in reason
    base = reason.split(";")[0] if swept else reason

    if base in _REASONS:
        label, explanation = _REASONS[base]
    elif base.startswith(SWEPT_PREFIX):
        label, explanation = _SWEPT
    else:
        label, explanation = (base or "알 수 없음"), "기록된 사유를 해석하지 못했습니다."

    if swept and not base.startswith(SWEPT_PREFIX):
        explanation = f"{explanation} {_SWEPT[1]}"

    return {
        "action": action,
        "action_label": _ACTIONS.get(action, action),
        "reason": reason,
        "reason_label": label,
        "explanation": explanation,
    }


def verdict(item: dict) -> dict[str, str]:
    """이력 항목 → 판정 + 설명. 화면과 리포트가 같은 문구를 쓴다."""
    action, reason = effective(item)
    return describe(action, reason)
