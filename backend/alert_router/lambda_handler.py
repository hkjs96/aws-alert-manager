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
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from common.alert_state import grp_key, iso_utc
from common.notification_channel import (
    channel_from_item,
    notification_from_event,
    select,
    storage_key,
)
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
    notification = notification_from_event(
        representative, url=os.environ.get("ALERT_CONSOLE_URL", ""), count=len(members))

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
             claimed=True)
    logger.info("Delivered group %s: members=%d channels=%d sent=%d failed=%d",
                gid, len(members), len(channels), sent, failed)
    return {"sent": sent, "failed": failed, "channels": len(channels),
            "members": len(members), "results": [r.to_dict() for r in results]}


def lambda_handler(event, context):
    event = event or {}
    group = event.get("group") or {}
    if not group.get("group_id") or not group.get("group_key"):
        raise ValueError(f"bad router invocation: group={group!r}")
    return deliver_group(group)
