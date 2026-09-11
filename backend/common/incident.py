"""
인시던트 — 알람이 아니라 **사건** 단위로 대응한다 (requirements R4, tasks 2.1)

알람 하나하나에 대응하면 같은 장애로 열 번 깨워도 "누가 언제 확인했는지"가 남지 않는다.
인시던트는 그 축을 사건으로 옮긴다: 발생(triggered) → 확인(acknowledged) → 해소(resolved).

**병합 축은 그룹과 같다 — `{customer_id}#{severity}`.** 다만 수명이 다르다. 그룹은 30초 창이고,
인시던트는 **원인 알람이 모두 풀릴 때까지** 산다(R4-4). 그래서 창이 여러 번 지나도 같은 사건이면
한 인시던트에 합쳐지고, 확인 한 번이 그 사건 전체에 적용된다.

열린 인시던트를 찾는 포인터는 `AlertStateTable`의 `inc#{customer}#{severity}`에 둔다 —
`fp#`/`grp#`와 같은 방식이라 조건부 갱신 기계를 그대로 쓴다.

이 모듈은 순수하다. 저장소도 시계도 모른다 — 전부 인자로 받는다.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

STATUS_TRIGGERED = "triggered"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED = "resolved"

INC_PREFIX = "inc#"

#: 타임라인·구성원 상한. DynamoDB 항목은 400KB이고, 폭풍이 한 사건에 몰릴 수 있다.
#: 넘치면 **오래된 것부터** 버린다 — 최근이 대응에 쓰인다.
MAX_TIMELINE = 100
MAX_MEMBERS = 200

#: 해소된 인시던트 보관 기간. MTTA/MTTR 집계와 "그때 왜"를 설명할 만큼만.
INCIDENT_TTL_DAYS = 90


def pointer_for_axis(axis: str) -> str:
    """열린 인시던트를 가리키는 상태 키. **축은 그룹 키와 같은 문자열**이다 (review-phase2 M3).

    그룹 키는 `{customer_id or account_id}#{severity}` — 고객사 매핑이 없는 계정은 계정별로 나뉜다.
    사건도 같은 축을 써야 미매핑 계정들이 `inc##SEV-x` 하나로 뭉치지 않고, 서로 다른 실행이 같은
    포인터를 두고 경합하지 않는다.
    """
    return f"{INC_PREFIX}{axis}"


def incident_pointer(customer_id: str, severity: str) -> str:
    """고객사·등급으로 축을 만드는 편의 함수. 매핑된 고객사에서는 그룹 키와 같다."""
    return pointer_for_axis(f"{customer_id}#{severity}")


def axis_of(incident: dict) -> str:
    """사건의 축. 축을 저장하기 전의 옛 행은 고객사#등급으로 되돌린다."""
    return str(incident.get("axis") or
               f"{incident.get('customer_id', '') or ''}#{incident.get('severity', '') or ''}")


def new_incident_id(customer_id: str, severity: str, opened_at: str, *, axis: str = "") -> str:
    digest = hashlib.sha1((axis or f"{customer_id}#{severity}").encode("utf-8")).hexdigest()[:12]
    stamp = re.sub(r"\D", "", opened_at)[:14] or "0"
    return f"inc-{digest}-{stamp}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _entry(at: datetime, kind: str, detail: str) -> dict:
    return {"at": _iso(at), "kind": kind, "detail": detail[:200]}


def new_incident(customer_id: str, severity: str, *, now: datetime, title: str = "",
                 axis: str = "", account_id: str = "") -> dict:
    """새 사건. `axis`는 그룹 키(없으면 고객사#등급). 고객사 매핑이 없는 계정은 `customer_id`가 비고
    `account_id`만 남는다 — 저장 시 빈 값은 빠지므로 그런 사건은 고객사 인덱스에 안 잡힌다(의도)."""
    opened = _iso(now)
    axis = axis or f"{customer_id}#{severity}"
    incident = {
        "incident_id": new_incident_id(customer_id, severity, opened, axis=axis),
        "customer_id": customer_id,
        "axis": axis,
        "severity": severity,
        "status": STATUS_TRIGGERED,
        "title": (title or "알람")[:200],
        "triggered_at": opened,
        "members": [],
        "timeline": [_entry(now, "triggered", title or "인시던트 생성")],
        "event_count": 0,
    }
    if account_id:                 # 빈 값은 저장에서 빠지므로 애초에 넣지 않는다(왕복 동일성)
        incident["account_id"] = account_id
    return incident


def merge_events(incident: dict, events: list[dict], *, now: datetime) -> dict:
    """발화 이벤트들을 인시던트에 합친다. 입력을 바꾸지 않는다.

    같은 지문이 여러 번 울려도 구성원은 한 번만 는다 — 사건의 크기는 "몇 번 울렸나"가 아니라
    "무엇이 아픈가"다. 다만 `event_count`는 누적해 소음의 양을 남긴다.
    """
    new = {**incident, "members": list(incident.get("members") or []),
           "timeline": list(incident.get("timeline") or [])}
    # 재알림이 채널 조건(계정·리소스 타입)에 맞출 수 있게 구성원의 축 값을 집합으로 남긴다(review-phase2 M4).
    accounts = set(incident.get("account_ids") or ()) | ({incident["account_id"]} if incident.get("account_id") else set())
    resource_types = set(incident.get("resource_types") or ())
    added = []
    for ev in events:
        series = str(ev.get("series_id", "") or "")
        if not series:
            continue
        new["event_count"] = int(new.get("event_count", 0)) + 1
        if ev.get("account_id"):
            accounts.add(str(ev["account_id"]))
        if ev.get("resource_type"):
            resource_types.add(str(ev["resource_type"]))
        if series not in new["members"]:
            if len(new["members"]) < MAX_MEMBERS:
                new["members"].append(series)
            added.append(ev)
    if accounts:
        new["account_ids"] = sorted(accounts)
    if resource_types:
        new["resource_types"] = sorted(resource_types)
    if added:
        names = ", ".join(str(e.get("alarm_name", "") or e.get("series_id", "")) for e in added[:3])
        more = f" 외 {len(added) - 3}건" if len(added) > 3 else ""
        new["timeline"] = _capped(new["timeline"] + [_entry(now, "alarm", f"{names}{more}")])
    return new


def match_fields(incident: dict) -> dict:
    """채널 조건 매칭에 넘길 사건의 축 값들. 계정·리소스 타입은 **목록**이다 — 사건은 여러 알람을
    묶으므로 채널 조건의 값 중 하나라도 사건 안에 있으면 그 채널이 받는다(review-phase2 M4)."""
    accounts = list(incident.get("account_ids") or ())
    if not accounts and incident.get("account_id"):
        accounts = [str(incident["account_id"])]
    return {
        "severity": str(incident.get("severity", "") or ""),
        "customer_id": str(incident.get("customer_id", "") or ""),
        "account_id": accounts,
        "resource_type": list(incident.get("resource_types") or ()),
    }


def _capped(timeline: list) -> list:
    """뒤 MAX_TIMELINE개를 남기되 **첫 항목(triggered)은 고정**한다 — 폭풍이 길어도 사건의 시작은 보여야 한다."""
    if len(timeline) <= MAX_TIMELINE:
        return timeline
    return [timeline[0]] + timeline[-(MAX_TIMELINE - 1):]


def acknowledge(incident: dict, *, by: str, now: datetime) -> dict:
    """확인 처리. **이미 확인됐거나 해소된 건은 그대로 둔다** — 첫 확인자가 기록으로 남아야 MTTA가 맞다."""
    if incident.get("status") != STATUS_TRIGGERED:
        return dict(incident)
    triggered = parse_dt(incident.get("triggered_at"))
    new = {**incident,
           "status": STATUS_ACKNOWLEDGED,
           "acknowledged_at": _iso(now),
           "acknowledged_by": by,
           "timeline": _capped(list(incident.get("timeline") or [])
                               + [_entry(now, "acknowledged", f"{by} 확인")])}
    if triggered:
        new["mtta_sec"] = max(0, int((now - triggered).total_seconds()))
    return new


def resolve(incident: dict, *, now: datetime, reason: str = "원인 알람이 모두 해소됨") -> dict:
    """해소 처리. 이미 해소된 건은 그대로 둔다(해소 시각이 밀리면 MTTR이 늘어난다)."""
    if incident.get("status") == STATUS_RESOLVED:
        return dict(incident)
    triggered = parse_dt(incident.get("triggered_at"))
    new = {**incident,
           "status": STATUS_RESOLVED,
           "resolved_at": _iso(now),
           "timeline": _capped(list(incident.get("timeline") or [])
                               + [_entry(now, "resolved", reason)])}
    if triggered:
        new["mttr_sec"] = max(0, int((now - triggered).total_seconds()))
    return new


def should_resolve(incident: dict, open_fingerprints: set[str]) -> bool:
    """원인 알람이 모두 OK로 돌아왔는가 (R4-4).

    구성원이 없으면 해소하지 않는다 — 아직 아무것도 안 붙은 새 인시던트를 지우면 안 된다.
    """
    members = list(incident.get("members") or [])
    if not members:
        return False
    return not any(m in open_fingerprints for m in members)


def needs_renotify(incident: dict, *, now: datetime, after_sec: int) -> bool:
    """확인은 됐는데 지정 시간이 지나도 안 풀렸는가 (R4-6).

    확인만 하고 손을 놓은 사건을 다시 띄운다. 재알림 뒤에는 `renotified_at`이 갱신되므로
    같은 사건이 계속 울리지 않고 주기마다 한 번씩만 온다.
    """
    if incident.get("status") != STATUS_ACKNOWLEDGED or after_sec <= 0:
        return False
    since = parse_dt(incident.get("renotified_at")) or parse_dt(incident.get("acknowledged_at"))
    if since is None:
        return False
    return (now - since).total_seconds() >= after_sec


def mark_renotified(incident: dict, *, now: datetime) -> dict:
    return {**incident,
            "renotified_at": _iso(now),
            "timeline": _capped(list(incident.get("timeline") or [])
                                + [_entry(now, "renotified", "미해결 재알림")])}


# ────────────────────────────────── 저장소 표현

def to_item(incident: dict, *, now: datetime, ttl_days: int = INCIDENT_TTL_DAYS) -> dict:
    item = {k: v for k, v in incident.items() if v not in ("", None)}
    item["ttl"] = int((now + timedelta(days=ttl_days)).timestamp())
    return item


def from_item(item: dict) -> dict:
    return {k: v for k, v in (item or {}).items() if k != "ttl"}


def to_dict(incident: dict) -> dict:
    """API 응답. 숫자는 int로 정규화한다 — DynamoDB는 Decimal로 돌려준다."""
    out = dict(incident)
    for key in ("mtta_sec", "mttr_sec", "event_count", "version"):
        if key in out and out[key] is not None:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out.pop(key)
    out["members"] = list(out.get("members") or [])
    out["timeline"] = list(out.get("timeline") or [])
    out["is_open"] = out.get("status") != STATUS_RESOLVED
    return out


def summarize(incidents: list[dict]) -> dict:
    """MTTA·MTTR 집계 (R4-5). 확인/해소된 건만 분모에 넣는다."""
    mtta = [int(i["mtta_sec"]) for i in incidents if i.get("mtta_sec") is not None]
    mttr = [int(i["mttr_sec"]) for i in incidents if i.get("mttr_sec") is not None]
    by_status: dict[str, int] = {}
    for i in incidents:
        status = str(i.get("status", "") or "")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(incidents),
        "by_status": by_status,
        "acknowledged_count": len(mtta),
        "resolved_count": len(mttr),
        "mtta_sec_avg": round(sum(mtta) / len(mtta), 1) if mtta else None,
        "mttr_sec_avg": round(sum(mttr) / len(mttr), 1) if mttr else None,
    }
