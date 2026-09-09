"""
Alert Group Worker — 그룹 실행의 Task 단계 (design.md D10, plan-state-grouping.md §B)

Step Functions 상태 머신이 호출한다. 실행 하나 = 그룹 하나.

  GroupWait(group_wait) → close → Grace(5s) → collect → [PauseWait(auto_pause)] → finalize

- close    grp#를 닫는다. **조회보다 먼저 닫는다** — 닫힌 뒤 도착한 이벤트는 새 그룹을 열고,
           닫히기 전 도착한 이벤트는 Grace 동안 적재를 마쳐 collect/finalize에 잡힌다. 빈틈이 없다.
- collect  구성원 수와 유예 필요 여부. DEFER가 있고 등급별 유예가 설정돼 있으면 pause_sec > 0.
- finalize 구성원마다 최종 판정을 이력에 write-back(`final_action`/`final_reason`).
           유예 중 스스로 해소된 DEFER는 `suppress/auto_pause` — auto-pause의 실제 이득이 여기서 잡힌다.
           아직 울리는 DEFER는 `notify`로 확정하고 fp# 상태에 "알렸음"을 남긴다(dedup 창 일관성).
- sweep    실행이 FAILED/TIMED_OUT/ABORTED로 끝났을 때(EventBridge "Execution Status Change") 대신 닫고
           확정한 뒤 라우터로 넘긴다(review-personas F4, review-phase2 H1). 유예 없이 finalize — 실행이
           죽은 시점에 이미 늦었고, 구성원을 잃는 것보다 보내는 게 낫다(fail-open). 인제스터도 기한 넘긴
           열린 그룹은 새로 연다(두 겹).

**Shadow 단계에서는 발송이 없다.** finalize가 남기는 `final_action`이 억제율 집계(1.5)의 최종값이다.
Phase 2에서 finalize 끝에 발송자가 붙는다 — claim-then-send 원칙은 상태 갱신 뒤에 보내는 것으로 지킨다.

인제스터와 Lambda를 분리한 이유: 권한이 다르고(이력 Query·UpdateItem, 인제스터엔 없다) 예약
동시성도 따로 가져가야 한다.
"""

import functools
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import BotoCoreError, ClientError

from common.alert_config import load_cached as load_policy
from common.alert_group import STATUS_CLOSED, STATUS_OPEN
from common.alert_state import fp_key, grp_key, iso_utc, state_item
from common.alert_suppression import REASON_AUTO_PAUSE, SuppressionPolicy
from common.perf_log import log_perf

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

GROUP_INDEX = "group_id-index"
FINAL_NOTIFY = "notify"
FINAL_SUPPRESS = "suppress"
REASON_PAUSE_EXPIRED = "auto_pause_expired"


@functools.lru_cache(maxsize=None)
def _get_ddb():
    return boto3.resource("dynamodb")


@functools.lru_cache(maxsize=1)
def _base_policy() -> SuppressionPolicy:
    return SuppressionPolicy.from_env()


@functools.lru_cache(maxsize=None)
def _lambda_client():
    return boto3.client("lambda")


def _hand_off_to_router(group: dict) -> str:
    """청소한 그룹을 라우터로 넘긴다 — 죽은 실행은 Deliver 단계에 못 갔다.

    finalize만 하고 끝내면 이력에는 `notify`로 남는데 알림은 영영 안 간다 — 화면은 "알림 대상"이라
    보여 주고 실패 알람도 이미 울렸으니 아무도 다시 묻지 않는, 가장 조용한 유실이다(review-phase2 H1).

    비동기 호출이다: 라우터가 밀려도 워커는 안 기다리고, 실패하면 Lambda가 두 번 더 재시도한다.
    라우터는 그룹마다 발송권을 선점(claim)하므로 이미 배달된 그룹이면 그쪽에서 조용히 끝난다 —
    항상 불러도 두 번 가지 않는다.
    """
    fn = os.environ.get("ALERT_ROUTER_FUNCTION", "")
    if not fn:
        logger.error("sweep: ALERT_ROUTER_FUNCTION is not set — group %s was finalized but will NOT be delivered",
                     group.get("group_id"))
        return "no_router"
    try:
        _lambda_client().invoke(FunctionName=fn, InvocationType="Event",
                                Payload=json.dumps({"group": group}).encode("utf-8"))
    except (ClientError, BotoCoreError) as e:
        logger.error("sweep: could not hand group %s to the router %s: %s", group.get("group_id"), fn, e)
        return "hand_off_failed"
    return "handed_off"


def _policy() -> SuppressionPolicy:
    """인제스터와 같은 설정 소스 — 유예 값이 두 곳에서 달라지면 그룹이 엉뚱한 시간을 기다린다."""
    name = os.environ.get("ALERT_POLICY_TABLE", "")
    policy, _ = load_policy(_get_ddb().Table(name) if name else None, _base_policy())
    return policy


def _tables():
    ddb = _get_ddb()
    return (ddb.Table(os.environ["EVENT_HISTORY_TABLE"]),
            ddb.Table(os.environ["ALERT_STATE_TABLE"]))


def _members(history, group_id: str) -> list[dict]:
    """그룹 구성원 전량 — `group_id-index`로 정확히 읽는다(시간 창 아님)."""
    items: list[dict] = []
    kwargs = {"IndexName": GROUP_INDEX, "KeyConditionExpression": Key("group_id").eq(group_id)}
    while True:
        resp = history.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def _is_deferred(item: dict) -> bool:
    return item.get("state") == "ALARM" and item.get("suppression_reason") == REASON_AUTO_PAUSE


def _conditional_put(table, key: str, state: dict, expected_version, *, ttl_days: int) -> bool:
    now = datetime.now(timezone.utc)
    if expected_version is None:
        cond, version = Attr("state_key").not_exists(), 1
    else:
        cond, version = Attr("version").eq(int(expected_version)), int(expected_version) + 1
    try:
        table.put_item(Item=state_item(key, state, now=now, version=version, ttl_days=ttl_days),
                       ConditionExpression=cond)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def close(group: dict) -> dict:
    """grp#를 닫는다. 이미 닫혔거나 다른 그룹이 열려 있으면 건드리지 않는다."""
    _, state = _tables()
    key = grp_key(group["group_key"])
    item = state.get_item(Key={"state_key": key}, ConsistentRead=True).get("Item")
    closed_at = iso_utc(datetime.now(timezone.utc))
    if not item or item.get("status") != STATUS_OPEN or item.get("group_id") != group["group_id"]:
        logger.info("group %s already closed or superseded", group["group_id"])
        return {"closed_at": closed_at, "was_open": False}
    ok = _conditional_put(state, key, {**item, "status": STATUS_CLOSED, "closed_at": closed_at},
                          item.get("version"), ttl_days=1)
    if not ok:
        # 인제스터가 방금 execution_arn을 채웠을 수 있다 — 한 번 더
        item = state.get_item(Key={"state_key": key}, ConsistentRead=True).get("Item") or {}
        if item.get("status") == STATUS_OPEN and item.get("group_id") == group["group_id"]:
            ok = _conditional_put(state, key, {**item, "status": STATUS_CLOSED, "closed_at": closed_at},
                                  item.get("version"), ttl_days=1)
    return {"closed_at": closed_at, "was_open": bool(ok)}


def collect(group: dict) -> dict:
    """구성원 수와 유예 필요 여부."""
    history, _ = _tables()
    members = _members(history, group["group_id"])
    deferred = sum(1 for m in members if _is_deferred(m))
    pause_sec = _policy().pause_for(str(group.get("severity", ""))) if deferred else 0
    return {"count": len(members), "deferred": deferred, "pause_sec": int(pause_sec)}


def _still_firing(state, item: dict) -> bool:
    """유예 뒤에도 그 에피소드가 열려 있는가 — fp# 상태로 판단한다(이력 재조회 아님)."""
    fp = state.get_item(Key={"state_key": fp_key(str(item["series_id"]))},
                        ConsistentRead=True).get("Item") or {}
    if not fp.get("episode_open"):
        return False
    return str(fp.get("episode_started_at", "")) <= str(item.get("occurred_at", ""))


def _mark_notified(state, series_id: str, occurred_at: str) -> None:
    """유예 뒤 확정 발송을 상태에 남긴다 — 이후 dedup 창이 이 시각 기준이 된다. 충돌은 한 번 재시도."""
    key = fp_key(series_id)
    for _ in range(2):
        fp = state.get_item(Key={"state_key": key}, ConsistentRead=True).get("Item")
        if not fp or not fp.get("episode_open"):
            return
        if _conditional_put(state, key, {**fp, "last_notified_at": occurred_at, "episode_notified": True},
                            fp.get("version"), ttl_days=30):
            return
    logger.warning("could not mark %s notified after pause (contention)", series_id)


def _write_back(history, item: dict, action: str, reason: str, group_id: str) -> None:
    history.update_item(
        Key={"series_id": item["series_id"], "event_key": item["event_key"]},
        UpdateExpression="SET final_action = :a, final_reason = :r, finalized_at = :t, group_id = :g",
        ExpressionAttributeValues={
            ":a": action, ":r": reason, ":t": iso_utc(datetime.now(timezone.utc)), ":g": group_id},
    )


def finalize(group: dict, *, sweep_reason: str = "") -> dict:
    """구성원마다 최종 판정을 확정해 이력에 남긴다.

    `sweep_reason`이 있으면 죽은 실행을 대신하는 청소다(F4): 이미 확정된 구성원은 건너뛰고, 나머지
    사유에 그 표식을 붙인다.
    """
    history, state = _tables()
    gid = group["group_id"]
    t0 = time.perf_counter()
    members = _members(history, gid)
    notified = suppressed = deferred = skipped = 0
    for m in members:
        if sweep_reason and m.get("final_action"):
            skipped += 1
            continue
        if _is_deferred(m):
            deferred += 1
            if _still_firing(state, m):
                action, reason = FINAL_NOTIFY, REASON_PAUSE_EXPIRED
                _mark_notified(state, str(m["series_id"]), str(m.get("occurred_at", "")))
            else:
                action, reason = FINAL_SUPPRESS, REASON_AUTO_PAUSE     # 유예 중 해소 — auto-pause의 이득
        else:
            action, reason = FINAL_NOTIFY, str(m.get("suppression_reason", "") or "")
        if sweep_reason:
            reason = f"{reason};{sweep_reason}" if reason else sweep_reason
        _write_back(history, m, action, reason, gid)
        if action == FINAL_NOTIFY:
            notified += 1
        else:
            suppressed += 1

    log_perf("alert_group", (time.perf_counter() - t0) * 1000,
             group_id=gid, customer=group.get("customer_id") or "-",
             severity=group.get("severity") or "-", size=len(members),
             deferred=deferred, notified=notified, suppressed=suppressed, swept=bool(sweep_reason))
    logger.info("Finalized group %s: size=%d deferred=%d notified=%d suppressed=%d%s",
                gid, len(members), deferred, notified, suppressed,
                f" ({sweep_reason}, skipped={skipped})" if sweep_reason else "")
    out = {"count": len(members), "deferred": deferred, "notified": notified, "suppressed": suppressed}
    if sweep_reason:
        out.update(swept=True, skipped=skipped)
    return out


def sweep(group: dict, *, status: str = "manual") -> dict:
    """죽은 실행의 그룹을 대신 확정한다 — 열려 있으면 닫고(다음 이벤트가 새 그룹을 열도록) 구성원을
    finalize한 뒤 **라우터로 넘긴다**. 죽은 실행은 Deliver 단계에 못 갔으니 여기서 안 넘기면 알림이 영영 안 간다.

    EventBridge "Step Functions Execution Status Change"(FAILED/TIMED_OUT/ABORTED)로 호출된다.
    `{"action": "sweep", "group": ...}` 직접 호출도 받는다(운영용, status=manual).
    """
    closed = close(group)
    out = finalize(group, sweep_reason=f"swept:{(status or 'manual').lower()}")
    out["was_open"] = closed["was_open"]
    # 구성원이 하나라도 있으면 넘긴다 — 이미 확정돼 건너뛴(skipped) 행도 배달은 안 됐을 수 있다.
    out["delivery"] = _hand_off_to_router(group) if out["count"] else "nothing_to_deliver"
    logger.warning("Swept group %s after execution %s: was_open=%s notified=%d suppressed=%d skipped=%d delivery=%s",
                   group["group_id"], status, closed["was_open"], out["notified"], out["suppressed"],
                   out["skipped"], out["delivery"])
    return out


def _sweep_from_event(event: dict) -> dict:
    """실행 상태 변경 이벤트 → sweep. 실행 입력(`detail.input`)이 곧 그룹이다."""
    detail = event.get("detail") or {}
    status = str(detail.get("status", "") or "")
    try:
        group = json.loads(detail.get("input") or "{}")
    except ValueError:
        group = {}
    if not isinstance(group, dict) or not group.get("group_id") or not group.get("group_key"):
        logger.error("sweep: execution %s (%s) carries no group input — nothing to sweep",
                     detail.get("executionArn", "?"), status)
        return {"swept": False, "reason": "no_group_input"}
    return sweep(group, status=status or "unknown")


_ACTIONS = {"close": close, "collect": collect, "finalize": finalize, "sweep": sweep}


def lambda_handler(event, context):
    event = event or {}
    if event.get("source") == "aws.states":
        return _sweep_from_event(event)
    action = event.get("action", "")
    group = event.get("group") or {}
    if action not in _ACTIONS or not group.get("group_id") or not group.get("group_key"):
        raise ValueError(f"bad worker invocation: action={action!r} group={group!r}")
    return _ACTIONS[action](group)
