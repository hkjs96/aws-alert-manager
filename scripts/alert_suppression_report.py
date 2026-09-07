"""
알림 억제율 리포트 — EventHistoryTable 집계 (docs/specs/alert-pipeline/ R9-1·R9-2, tasks 1.5)

Shadow 정제가 실제 트래픽에서 얼마나 억제하는지 본다. Logs Insights가 아니라 **이력 테이블**을
읽는 이유: 그룹 워커가 write-back 한 `final_action`(DEFER의 유예 결과 포함)은 테이블에만 있고,
90일 보관이라 기간 비교가 된다. 로그 쿼리는 실시간 확인용(docs/OBSERVABILITY.md §7~9).

판정의 최종값 규칙 (이 순서):
  1. `final_action` 있음        → 그것. 그룹 실행이 확정한 값 (유예 중 해소 = suppress/auto_pause)
  2. 없고 `suppressed=True`     → suppress. 적재 시 억제 (dedup/flapping/silence/cleared/not_actionable)
  3. 없고 reason=auto_pause     → pending. 유예 중 — 아직 확정 안 됨 (실행이 끝나면 1로 바뀐다)
  4. 그 외                      → notify

    AWS_PROFILE=xxx python scripts/alert_suppression_report.py --days 7
    AWS_PROFILE=xxx python scripts/alert_suppression_report.py --days 7 --customer EMU-EM2 \\
        --output docs/reports/ALERT-SUPPRESSION-2026-09-07.md

읽기 전용. 순수 집계 함수는 backend/tests/test_alert_suppression_report.py가 고정한다.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

NOTIFY, SUPPRESS, PENDING = "notify", "suppress", "pending"
_CLEAR_STATES = ("OK", "INSUFFICIENT_DATA")
TOP_N = 15


# ──────────────────────────────────────────────
# 순수 로직
# ──────────────────────────────────────────────

def effective(item: dict) -> tuple[str, str]:
    """이력 항목의 최종 판정 (action, reason)."""
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


def _rate(num: int, den: int) -> float:
    return (num / den) if den else 0.0


def aggregate(items: list[dict]) -> dict:
    kinds: Counter = Counter()
    firing_action: Counter = Counter()
    firing_reason: Counter = Counter()
    clearing_action: Counter = Counter()
    by_sev: dict[str, Counter] = defaultdict(Counter)
    by_cust: dict[str, Counter] = defaultdict(Counter)
    series: dict[str, Counter] = defaultdict(Counter)
    series_reason: dict[str, Counter] = defaultdict(Counter)
    groups: Counter = Counter()
    group_final: Counter = Counter()
    quality: Counter = Counter()

    for it in items:
        k = kind(it)
        kinds[k] += 1
        if it.get("parse_error"):
            quality["unmanaged"] += 1
        if it.get("raw_truncated"):
            quality["raw_truncated"] += 1
        if k == "config":
            continue
        action, reason = effective(it)
        gid = it.get("group_id")
        if gid:
            groups[str(gid)] += 1
            if it.get("final_action"):
                group_final[(str(it["final_action"]), str(it.get("final_reason", "") or ""))] += 1
            else:
                quality["grouped_not_finalized"] += 1
        if k == "clearing":
            clearing_action[action] += 1
            continue
        if k != "firing":
            continue
        firing_action[action] += 1
        if action == SUPPRESS:
            firing_reason[reason or "(none)"] += 1
        if action == PENDING:
            quality["pending"] += 1
        sev = str(it.get("severity") or "(none)")
        cust = str(it.get("customer_id") or "(unmapped)")
        by_sev[sev][action] += 1
        by_cust[cust][action] += 1
        sid = str(it.get("series_id", ""))
        series[sid][action] += 1
        series[sid]["alarm_name"] = it.get("alarm_name", "") or series[sid].get("alarm_name", "")  # type: ignore[assignment]
        if action == SUPPRESS:
            series_reason[sid][reason or "(none)"] += 1

    decided = firing_action[NOTIFY] + firing_action[SUPPRESS]
    top = sorted(series.items(),
                 key=lambda kv: (kv[1][NOTIFY] + kv[1][SUPPRESS] + kv[1][PENDING]), reverse=True)[:TOP_N]
    sizes = sorted(groups.values())
    return {
        "events": sum(kinds.values()),
        "kinds": dict(kinds),
        "firing": dict(firing_action),
        "firing_decided": decided,
        "suppression_rate": _rate(firing_action[SUPPRESS], decided),
        "firing_reason": dict(firing_reason),
        "clearing": dict(clearing_action),
        "by_severity": {s: dict(c) for s, c in sorted(by_sev.items())},
        "by_customer": {c: dict(v) for c, v in sorted(by_cust.items())},
        "top_series": [
            {"series_id": sid, "alarm_name": str(c.get("alarm_name", "")),
             "notify": c[NOTIFY], "suppress": c[SUPPRESS], "pending": c[PENDING],
             "top_reason": (series_reason[sid].most_common(1) or [("", 0)])[0][0]}
            for sid, c in top
        ],
        "groups": {
            "count": len(groups),
            "events": sum(groups.values()),
            "avg_size": _rate(sum(sizes), len(sizes)),
            "max_size": sizes[-1] if sizes else 0,
            "final": {f"{a}/{r}" if r else a: n for (a, r), n in sorted(group_final.items())},
            "auto_pause_suppressed": group_final[(SUPPRESS, "auto_pause")],
            "auto_pause_expired": group_final[(NOTIFY, "auto_pause_expired")],
        },
        "quality": dict(quality),
    }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(a: dict, *, start: datetime, end: datetime, customers: list[str]) -> str:
    L: list[str] = []
    w = L.append
    w(f"# 알림 억제율 실측 — {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
    w("")
    w(f"- 대상 고객사: {', '.join(customers) if customers else '(전체)'} · 이벤트 {a['events']:,}건 "
      f"(상태 전이 {a['kinds'].get('firing', 0) + a['kinds'].get('clearing', 0) + a['kinds'].get('other', 0):,} · "
      f"설정 변경 {a['kinds'].get('config', 0):,})")
    w("- 최종값 규칙: `final_action`(그룹 워커 확정) > `suppressed`(적재 시 억제) > `auto_pause`(유예 중=pending) > notify")
    w("")
    if a["firing_decided"] == 0:
        w("> ⚠️ 이 기간에 판정이 확정된 발화가 없다. 기간(`--days`)을 늘리거나 알람이 실제로 울리는 고객사를 지정할 것.")
        return "\n".join(L)

    f = a["firing"]
    w(f"## 1. 발화 판정 — 억제율 **{_pct(a['suppression_rate'])}** "
      f"(억제 {f.get(SUPPRESS, 0):,} / 확정 {a['firing_decided']:,})")
    w("")
    w("| 판정 | 건수 | 비율 |")
    w("|---|---|---|")
    for act in (NOTIFY, SUPPRESS, PENDING):
        n = f.get(act, 0)
        w(f"| {act} | {n:,} | {_pct(_rate(n, sum(f.values())))} |")
    w("")
    if a["firing_reason"]:
        w("### 억제 사유")
        w("")
        w("| 사유 | 건수 | 억제 중 비율 |")
        w("|---|---|---|")
        total = sum(a["firing_reason"].values())
        for reason, n in sorted(a["firing_reason"].items(), key=lambda kv: -kv[1]):
            w(f"| `{reason}` | {n:,} | {_pct(_rate(n, total))} |")
        w("")

    c = a["clearing"]
    w(f"## 2. 해소 전이 — 해소 알림 {c.get(NOTIFY, 0):,} · 조용히 종료 {c.get(SUPPRESS, 0):,}")
    w("")
    w("알린 에피소드의 해소만 알린다(`already_notified`). 조용히 종료된 것은 억제됐던 발화의 해소다.")
    w("")

    w("## 3. 등급별 (발화)")
    w("")
    w("| 등급 | notify | suppress | pending | 억제율 |")
    w("|---|---|---|---|---|")
    for sev, cnt in a["by_severity"].items():
        d = cnt.get(NOTIFY, 0) + cnt.get(SUPPRESS, 0)
        w(f"| {sev} | {cnt.get(NOTIFY, 0):,} | {cnt.get(SUPPRESS, 0):,} | {cnt.get(PENDING, 0):,} | "
          f"{_pct(_rate(cnt.get(SUPPRESS, 0), d))} |")
    w("")

    if len(a["by_customer"]) > 1 or customers:
        w("## 4. 고객사별 (발화)")
        w("")
        w("| 고객사 | notify | suppress | pending | 억제율 |")
        w("|---|---|---|---|---|")
        for cust, cnt in a["by_customer"].items():
            d = cnt.get(NOTIFY, 0) + cnt.get(SUPPRESS, 0)
            w(f"| {cust} | {cnt.get(NOTIFY, 0):,} | {cnt.get(SUPPRESS, 0):,} | {cnt.get(PENDING, 0):,} | "
              f"{_pct(_rate(cnt.get(SUPPRESS, 0), d))} |")
        w("")

    w(f"## 5. 시끄러운 시계열 top {min(TOP_N, len(a['top_series']))}")
    w("")
    w("| 발화 | notify | suppress | 주 사유 | 알람 |")
    w("|---|---|---|---|---|")
    for s in a["top_series"]:
        w(f"| {s['notify'] + s['suppress'] + s['pending']:,} | {s['notify']:,} | {s['suppress']:,} | "
          f"`{s['top_reason'] or '-'}` | `{(s['alarm_name'] or s['series_id'])[:80]}` |")
    w("")

    g = a["groups"]
    w(f"## 6. 그룹 — 실행 {g['count']:,}개 · 구성원 {g['events']:,}건 · 평균 {g['avg_size']:.1f} · 최대 {g['max_size']:,}")
    w("")
    w("실행 수는 이벤트 수가 아니라 (고객사×등급) × 시간 창 수에 비례한다(design.md D10).")
    w("")
    if g["final"]:
        w("| 확정 | 건수 |")
        w("|---|---|")
        for key, n in g["final"].items():
            w(f"| `{key}` | {n:,} |")
        w("")
    if g["auto_pause_suppressed"] or g["auto_pause_expired"]:
        w(f"- **auto-pause 이득:** 유예 중 해소 {g['auto_pause_suppressed']:,}건 (보내지 않음) · "
          f"유예 후에도 울림 {g['auto_pause_expired']:,}건")
        w("")
    else:
        w("- auto-pause: 유예 값(`ALERT_AUTO_PAUSE_SEC`)이 비어 있어 DEFER가 없다 — Phase 0 실측 후 설정.")
        w("")

    q = a["quality"]
    w("## 7. 데이터 품질")
    w("")
    w(f"- 미관리 알람(우리 메타데이터 없음): {q.get('unmanaged', 0):,}건 — 이력에는 남지만 라우팅 대상은 아니다")
    w(f"- 유예 중(pending, 아직 확정 안 됨): {q.get('pending', 0):,}건")
    w(f"- 그룹에 속했지만 미확정: {q.get('grouped_not_finalized', 0):,}건 — 실행이 진행 중이거나 실패했다면 `[AlertGroup] 그룹 실행 실패` 알람 확인")
    w(f"- 원본(raw) 축약: {q.get('raw_truncated', 0):,}건")
    w("")
    w("## 해석 주의")
    w("")
    w("- 정비창(silence)은 아직 저장소가 없어 미배선(tasks 1.4.4) — 억제율은 **하한**이다.")
    w("- dedup 창은 4시간(U6 미결) — 해소 뒤 재발화가 4시간 안이면 억제로 잡힌다.")
    return "\n".join(L)


# ──────────────────────────────────────────────
# AWS 조회
# ──────────────────────────────────────────────

def _days(start: datetime, end: datetime) -> list[str]:
    out, d = [], start.date()
    while d <= end.date():
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def customers_from_accounts(table) -> list[str]:
    seen: set[str] = set()
    kwargs: dict = {"ProjectionExpression": "customer_id"}
    while True:
        resp = table.scan(**kwargs)
        for it in resp.get("Items", []):
            seen.add(str(it.get("customer_id", "") or ""))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted(seen)


def fetch(table, customers: list[str], days: list[str]) -> list[dict]:
    items: list[dict] = []
    for cust in customers:
        for day in days:
            kwargs: dict = {
                "IndexName": "customer_day-index",
                "KeyConditionExpression": Key("customer_day").eq(f"{cust}#{day}"),
            }
            while True:
                resp = table.query(**kwargs)
                items.extend(resp.get("Items", []))
                last = resp.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
    return items


def main() -> int:
    p = argparse.ArgumentParser(description="알림 억제율 리포트 (EventHistoryTable, 읽기 전용)")
    p.add_argument("--days", type=int, default=7, help="조회 기간(일). 기본 7, 최대 90(보관 기간)")
    p.add_argument("--customer", action="append", default=[], help="고객사 ID (반복 가능). 없으면 계정 테이블의 전체 + 미매핑")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--stack", default="aws-monitoring-engine-dev")
    p.add_argument("--output", default="", help="출력 경로. 기본 docs/reports/ALERT-SUPPRESSION-{today}.md")
    args = p.parse_args()
    args.days = max(1, min(args.days, 90))

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    try:
        sess = boto3.Session(region_name=args.region)
        cfn = sess.client("cloudformation")
        ddb = sess.resource("dynamodb")

        def physical(logical: str) -> str:
            return cfn.describe_stack_resource(
                StackName=args.stack, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]

        history = ddb.Table(physical("EventHistoryTable"))
        customers = list(args.customer) or (customers_from_accounts(ddb.Table(physical("AccountsTable"))) + [""])
        print(f"[1/2] 이력 조회: 고객사 {len(customers)}개 × {args.days}일 ...")
        items = fetch(history, customers, _days(start, end))
    except (ClientError, BotoCoreError) as e:
        print(f"AWS 오류: {e}", file=sys.stderr)
        return 1
    print(f"      이벤트 {len(items):,}건")

    print("[2/2] 집계 ...")
    report = render(aggregate(items), start=start, end=end, customers=[c for c in customers if c])
    out = Path(args.output) if args.output else (
        Path(__file__).resolve().parents[1] / "docs" / "reports" / f"ALERT-SUPPRESSION-{end:%Y-%m-%d}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(f"      → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
