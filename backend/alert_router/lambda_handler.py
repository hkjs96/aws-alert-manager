"""
Alert Router — 확정된 그룹을 채널로 내보낸다 (tasks 2.2.3, design.md D3)

상태 머신의 마지막 단계다. 그룹 워커가 `final_action`을 확정한 **뒤에** 호출된다.

  … → Finalize(워커) → **Deliver(여기)**

**그룹당 한 번, 채널당 한 통.** 폭풍에 알람 200건이 한 그룹에 묶였다면 200통이 아니라
"대표 1건 + 외 199건" 한 통이 간다(R6-9). 그게 그룹핑을 한 이유다.

**중복 발송을 막는 방법:** 보내기 전에 `grp#` 항목에 `delivered_at`을 조건부로 적는다.
이미 있으면 다른 실행이 이미 보냈다는 뜻이므로 아무것도 하지 않는다. 상태 머신 재시도나
sweep이 겹쳐도 같은 알림이 두 번 가지 않는다.

**claim-then-send이므로 최대 한 번이다.** 표시한 뒤 보내다 죽으면 그만큼은 안 간다.
알림을 두 번 보내 사람을 두 번 깨우는 것보다, 안 간 것을 실패로 남겨 드러내는 쪽을 택했다 —
결과는 채널마다 이력에 기록되고 `alert_delivery` 지표로 나간다.

라우터를 워커와 분리한 이유: 바깥 HTTP 호출은 느리거나 멈출 수 있는데, 그게 그룹 상태를
확정하는 워커를 붙잡으면 안 된다. 권한도 다르다(채널 표 읽기, SES).
"""

import functools
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from common.alert_config import load_cached as load_policy
from common.alert_state import fp_key, grp_key, iso_utc
from common.incident import (
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    mark_renotified,
    needs_renotify,
    parse_dt,
    from_item as incident_from_item,
    incident_pointer,
    merge_events,
    new_incident,
    resolve as resolve_incident,
    should_resolve,
    to_item as incident_to_item,
)
from common.notification_adapters import Notification
from common.notification_channel import (
    channel_from_item,
    notification_from_event,
    select,
    storage_key,
)
from common.alert_suppression import SuppressionPolicy
from common.notification_send import deliver_all
from common.perf_log import log_perf

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

GROUP_INDEX = "group_id-index"
FINAL_NOTIFY = "notify"

#: 등급이 높을수록 대표로 뽑는다. 묶음의 제목은 가장 심각한 것이어야 한다.
_SEVERITY_RANK = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3, "SEV-4": 4, "SEV-5": 5}


@functools.lru_cache(maxsize=None)
def _get_ddb():
    return boto3.resource("dynamodb")


def _tables():
    ddb = _get_ddb()
    return (ddb.Table(os.environ["EVENT_HISTORY_TABLE"]),
            ddb.Table(os.environ["ALERT_STATE_TABLE"]),
            ddb.Table(os.environ["NOTIFICATION_CHANNEL_TABLE"]))


def _incident_table():
    return _get_ddb().Table(os.environ["INCIDENT_TABLE"])


def _open_fingerprints(state, series_ids: list[str]) -> set[str]:
    """아직 발화 중인 지문. 인시던트를 해소해도 되는지 판단하는 근거다(R4-4)."""
    still_open = set()
    for series in series_ids:
        try:
            item = state.get_item(Key={"state_key": fp_key(series)},
                                  ConsistentRead=True).get("Item") or {}
        except ClientError as e:
            # 못 읽었으면 **열려 있다고 본다** — 살아 있는 사건을 성급히 닫지 않는다
            logger.warning("fp state unreadable for %s: %s", series, e)
            still_open.add(series)
            continue
        if item.get("episode_open"):
            still_open.add(series)
    return still_open


def _sync_incident(state, incidents, group: dict, firing: list[dict],
                   all_members: list[dict], now: datetime) -> dict | None:
    """발화가 있으면 사건을 열거나 합치고, 원인이 모두 풀렸으면 해소한다 (R4-1·R4-4).

    사건의 축은 그룹과 같지만(고객사×등급) 수명이 다르다 — 30초 창이 여러 번 지나도
    원인 알람이 살아 있는 동안은 한 사건이다. 그래야 확인 한 번이 사건 전체에 적용된다.
    """
    customer_id = str(group.get("customer_id", "") or "")
    severity = str(group.get("severity", "") or "")
    pointer = incident_pointer(customer_id, severity)

    try:
        pointed = state.get_item(Key={"state_key": pointer}, ConsistentRead=True).get("Item") or {}
    except ClientError as e:
        logger.error("incident pointer unreadable: %s", e)
        return None
    incident_id = str(pointed.get("incident_id", "") or "")

    incident = None
    if incident_id:
        try:
            item = incidents.get_item(Key={"incident_id": incident_id}).get("Item")
            incident = incident_from_item(item) if item else None
        except ClientError as e:
            logger.error("incident %s unreadable: %s", incident_id, e)
            return None

    if firing:
        if incident is None or incident.get("status") == STATUS_RESOLVED:
            title = str(firing[0].get("alarm_name", "") or "")
            incident = new_incident(customer_id, severity, now=now, title=title)
        incident = merge_events(incident, firing, now=now)
    elif incident is None:
        return None        # 해소 이벤트만 왔는데 열린 사건이 없다 — 할 일이 없다

    # 원인이 모두 풀렸는가. 방금 합친 발화가 있으면 당연히 아니다.
    if not firing and should_resolve(incident, _open_fingerprints(state, incident.get("members") or [])):
        incident = resolve_incident(incident, now=now)

    try:
        incidents.put_item(Item=incident_to_item(incident, now=now))
        if incident.get("status") == STATUS_RESOLVED:
            state.delete_item(Key={"state_key": pointer})
        else:
            state.put_item(Item={"state_key": pointer,
                                 "incident_id": incident["incident_id"],
                                 "ttl": int((now + timedelta(days=30)).timestamp())})
    except ClientError as e:
        logger.error("could not save incident: %s", e)
        return None
    return incident


def _member_keys(history, group_id: str) -> list[dict]:
    """구성원의 키만 인덱스에서 찾는다.

    `group_id`는 적재 시점에 적히므로 인덱스에 이미 안정적으로 반영돼 있다. 반면
    `final_action`은 바로 직전 단계(finalize)가 쓴 값이라 **인덱스에는 아직 없을 수 있다** —
    GSI는 최종 일관성이고 ConsistentRead를 지원하지 않는다. 그래서 여기서는 키만 얻는다.
    """
    keys: list[dict] = []
    kwargs = {"IndexName": GROUP_INDEX, "KeyConditionExpression": Key("group_id").eq(group_id),
              "ProjectionExpression": "series_id, event_key"}
    while True:
        resp = history.query(**kwargs)
        keys.extend({"series_id": i["series_id"], "event_key": i["event_key"]}
                    for i in resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return keys
        kwargs["ExclusiveStartKey"] = last


def _members(history, group_id: str) -> list[dict]:
    """구성원의 **현재** 상태. 키는 인덱스에서, 값은 기본 테이블에서 일관되게 읽는다.

    인덱스의 사본을 그대로 믿으면 finalize 직후 `final_action`이 안 보여 발송이 통째로
    누락된다(라이브에서 그렇게 드러났다 — 상태 머신은 성공했는데 알림만 안 갔다).
    """
    keys = _member_keys(history, group_id)
    if not keys:
        return []
    ddb, items = _get_ddb(), []
    for chunk in (keys[i:i + 100] for i in range(0, len(keys), 100)):
        pending = {history.name: {"Keys": chunk, "ConsistentRead": True}}
        while pending:
            resp = ddb.batch_get_item(RequestItems=pending)
            items.extend(resp.get("Responses", {}).get(history.name, []))
            pending = {k: v for k, v in (resp.get("UnprocessedKeys") or {}).items() if v}
    return items


def _channels(table, customer_id: str) -> list:
    """이 고객사의 채널 + 전역 채널. 유형이 사라진 옛 행은 건너뛴다."""
    out = []
    keys = [customer_id] if not customer_id else [customer_id, ""]
    for key in keys:
        kwargs = {"KeyConditionExpression": Key("customer_id").eq(storage_key(key))}
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                try:
                    channel = channel_from_item(item)
                    channel.adapter          # 유형이 아직 있는지 확인
                    out.append(channel)
                except Exception as e:                          # noqa: BLE001
                    logger.warning("skipping channel %s: %s", item.get("channel_id"), e)
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    return out


def _representative(members: list[dict]) -> dict:
    """묶음의 대표 — 가장 심각한 것, 같으면 가장 이른 것."""
    return min(members, key=lambda m: (_SEVERITY_RANK.get(str(m.get("severity", "")), 9),
                                       str(m.get("occurred_at", ""))))


def _claim(state, group: dict, now: datetime) -> bool:
    """이 그룹의 발송권을 딱 한 번만 가져온다. 이미 보냈으면 False."""
    try:
        state.update_item(
            Key={"state_key": grp_key(group["group_key"])},
            UpdateExpression="SET delivered_at = :t",
            ConditionExpression=Attr("delivered_at").not_exists(),
            ExpressionAttributeValues={":t": iso_utc(now)},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _record(history, members: list[dict], results: list, now: datetime) -> None:
    """구성원 이력에 발송 결과를 남긴다 — "안 왔다"를 조사할 때 첫 번째로 보는 곳."""
    summary = [r.to_dict() for r in results]
    delivered = any(r.ok for r in results)
    for m in members:
        try:
            history.update_item(
                Key={"series_id": m["series_id"], "event_key": m["event_key"]},
                UpdateExpression=("SET delivered = :d, delivered_at = :t, "
                                  "delivery_results = :r"),
                ExpressionAttributeValues={
                    ":d": delivered, ":t": iso_utc(now), ":r": summary},
            )
        except ClientError as e:
            logger.error("could not record delivery on %s: %s", m.get("event_key"), e)


def deliver_group(group: dict) -> dict:
    history, state, channel_table = _tables()
    gid = str(group.get("group_id", ""))
    now = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    members = [m for m in _members(history, gid) if m.get("final_action") == FINAL_NOTIFY]
    if not members:
        logger.info("group %s has nothing to send", gid)
        return {"sent": 0, "channels": 0, "members": 0, "reason": "nothing_to_notify"}

    customer_id = str(group.get("customer_id", "") or "")
    representative = _representative(members)

    # 사건 축으로 묶는다. 실패해도 발송은 계속한다 — 알림이 사건 기록보다 급하다.
    firing = [m for m in members if str(m.get("state", "")) == "ALARM"]
    incident = None
    if os.environ.get("INCIDENT_TABLE"):
        try:
            incident = _sync_incident(state, _incident_table(), group, firing, members, now)
        except Exception as e:                                  # noqa: BLE001
            logger.error("incident sync failed for group %s: %s", gid, e)
    incident_id = str((incident or {}).get("incident_id", "") or "")

    console = os.environ.get("ALERT_CONSOLE_URL", "")
    url = f"{console}?incident={incident_id}" if console and incident_id else console
    notification = notification_from_event(
        representative, url=url, count=len(members), incident_id=incident_id)

    candidates = _channels(channel_table, customer_id)
    channels = select(candidates, representative)
    if not channels:
        # 채널이 없는 것은 오류가 아니다(아직 등록 전일 수 있다). 다만 보이게 남긴다.
        logger.warning("group %s (customer=%s) matched no channel out of %d",
                       gid, customer_id or "-", len(candidates))
        log_perf("alert_delivery", (time.perf_counter() - t0) * 1000,
                 group_id=gid, customer=customer_id or "-",
                 severity=str(representative.get("severity", "")) or "-",
                 members=len(members), channels=0, sent=0, failed=0, claimed=False)
        return {"sent": 0, "channels": 0, "members": len(members), "reason": "no_channel"}

    if not _claim(state, group, now):
        logger.info("group %s already delivered — skipping", gid)
        return {"sent": 0, "channels": len(channels), "members": len(members),
                "reason": "already_delivered"}

    results = deliver_all(channels, notification,
                          sender=os.environ.get("ALERT_EMAIL_SENDER", ""))
    sent = sum(1 for r in results if r.ok)
    failed = len(results) - sent
    _record(history, members, results, now)

    for r in results:
        if not r.ok:
            logger.error("delivery failed: channel=%s type=%s status=%s error=%s",
                         r.channel_name, r.type, r.status, r.error)

    log_perf("alert_delivery", (time.perf_counter() - t0) * 1000,
             group_id=gid, customer=customer_id or "-",
             severity=str(representative.get("severity", "")) or "-",
             members=len(members), channels=len(channels), sent=sent, failed=failed,
             claimed=True, incident=incident_id or "-",
             incident_status=str((incident or {}).get("status", "")) or "-")
    logger.info("Delivered group %s: members=%d channels=%d sent=%d failed=%d",
                gid, len(members), len(channels), sent, failed)
    return {"sent": sent, "failed": failed, "channels": len(channels),
            "members": len(members), "incident_id": incident_id,
            "incident_status": str((incident or {}).get("status", "")),
            "results": [r.to_dict() for r in results]}


def _policy() -> SuppressionPolicy:
    """인제스터·워커와 같은 설정 소스. 재알림 주기를 배포 없이 바꿀 수 있어야 한다."""
    name = os.environ.get("ALERT_POLICY_TABLE", "")
    base = SuppressionPolicy.from_env()
    policy, _ = load_policy(_get_ddb().Table(name) if name else None, base)
    return policy


def _acknowledged_incidents(incidents) -> list[dict]:
    """확인됐지만 해소되지 않은 사건. 표는 TTL 90일이라 작다 — 스캔으로 충분하다."""
    out, kwargs = [], {
        "FilterExpression": Attr("status").eq(STATUS_ACKNOWLEDGED),
    }
    while True:
        resp = incidents.scan(**kwargs)
        out.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return out
        kwargs["ExclusiveStartKey"] = last


def _claim_renotify(incidents, incident: dict, now: datetime) -> bool:
    """재알림 권한을 한 번만 가져온다.

    두 실행이 겹치면 같은 사건이 두 번 울린다. `renotified_at`이 **읽은 그대로일 때만** 쓴다.
    """
    previous = incident.get("renotified_at")
    marked = mark_renotified(incident, now=now)
    try:
        if previous:
            incidents.update_item(
                Key={"incident_id": incident["incident_id"]},
                UpdateExpression="SET renotified_at = :new, #tl = :tl",
                ConditionExpression=Attr("renotified_at").eq(previous),
                ExpressionAttributeNames={"#tl": "timeline"},
                ExpressionAttributeValues={":new": marked["renotified_at"],
                                           ":tl": marked["timeline"]})
        else:
            incidents.update_item(
                Key={"incident_id": incident["incident_id"]},
                UpdateExpression="SET renotified_at = :new, #tl = :tl",
                ConditionExpression=Attr("renotified_at").not_exists(),
                ExpressionAttributeNames={"#tl": "timeline"},
                ExpressionAttributeValues={":new": marked["renotified_at"],
                                           ":tl": marked["timeline"]})
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _renotification(incident: dict, now: datetime, console: str) -> Notification:
    since = parse_dt(incident.get("acknowledged_at"))
    minutes = int((now - since).total_seconds() // 60) if since else 0
    iid = str(incident.get("incident_id", ""))
    members = list(incident.get("members") or [])
    return Notification(
        title=f"[미해결] {incident.get('title', '') or '인시던트'}",
        severity=str(incident.get("severity", "") or ""),
        customer_id=str(incident.get("customer_id", "") or ""),
        reason=f"{incident.get('acknowledged_by', '') or '누군가'} 확인 후 {minutes}분 경과, "
               f"아직 해소되지 않았습니다.",
        occurred_at=str(incident.get("triggered_at", "") or ""),
        url=f"{console}?incident={iid}" if console else "",
        count=max(1, len(members)),
        incident_id=iid,
    )


def renotify_due() -> dict:
    """확인만 하고 방치된 사건을 다시 띄운다 (R4-6). 주기 실행으로 호출된다."""
    if not os.environ.get("INCIDENT_TABLE"):
        return {"checked": 0, "renotified": 0, "reason": "no_incident_table"}
    after_sec = int(getattr(_policy(), "renotify_after_sec", 0) or 0)
    if after_sec <= 0:
        return {"checked": 0, "renotified": 0, "reason": "disabled"}

    _, state, channel_table = _tables()
    incidents = _incident_table()
    now = datetime.now(timezone.utc)
    candidates = _acknowledged_incidents(incidents)
    renotified = sent_total = 0

    for item in candidates:
        incident = incident_from_item(item)
        if not needs_renotify(incident, now=now, after_sec=after_sec):
            continue
        customer_id = str(incident.get("customer_id", "") or "")
        channels = select(_channels(channel_table, customer_id),
                          {"severity": incident.get("severity", ""),
                           "customer_id": customer_id})
        if not channels:
            continue
        # 보내기 전에 표시한다 — 겹친 실행이 같은 사건을 두 번 울리지 않게.
        if not _claim_renotify(incidents, incident, now):
            continue
        results = deliver_all(channels,
                              _renotification(incident, now, os.environ.get("ALERT_CONSOLE_URL", "")),
                              sender=os.environ.get("ALERT_EMAIL_SENDER", ""))
        ok_count = sum(1 for r in results if r.ok)
        sent_total += ok_count
        renotified += 1
        logger.warning("renotified incident %s (acked by %s): channels=%d sent=%d",
                       incident.get("incident_id"), incident.get("acknowledged_by"),
                       len(channels), ok_count)

    log_perf("alert_renotify", 0.0, checked=len(candidates), renotified=renotified,
             sent=sent_total, after_sec=after_sec)
    return {"checked": len(candidates), "renotified": renotified, "sent": sent_total}


def lambda_handler(event, context):
    event = event or {}
    if event.get("action") == "renotify" or event.get("detail-type") == "Scheduled Event":
        return renotify_due()
    group = event.get("group") or {}
    if not group.get("group_id") or not group.get("group_key"):
        raise ValueError(f"bad router invocation: group={group!r}")
    return deliver_group(group)
