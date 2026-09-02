#!/usr/bin/env python3
"""
알람 이력 분석 — 노이즈의 정체를 실측한다 (docs/specs/alert-pipeline/tasks.md Phase 0)

배포 없이 돌린다. `DescribeAlarms` + `DescribeAlarmHistory`는 일반 CloudWatch API라
무료 구간(월 100만 요청) 안이고, 읽기만 하므로 대상 계정에 아무 영향이 없다.

답하려는 질문:
  1. **N분 유예하면 몇 %가 사라지는가** — auto-pause 값을 추측이 아니라 데이터로 정한다
  2. 상위 몇 개 알람이 전체의 몇 %인가 — 어디를 깎으면 절반이 사라지는가
  3. 어떤 메트릭·리소스 타입이 노이즈원인가
  4. 시간대 패턴 — 업무시간 스파이크가 "정상인데 우는" 것인가
  5. flapping — 하루에 몇 번씩 켜졌다 꺼지는 알람은 무엇인가

사용:
    AWS_PROFILE=xxx python scripts/analyze_alarm_history.py --days 7
    AWS_PROFILE=xxx python scripts/analyze_alarm_history.py --days 7 --region ap-northeast-2 \\
        --role-arn arn:aws:iam::123456789012:role/AlarmManagerMonitoringRole
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# 유예 시간 후보 (분). 이 값들에 대해 "그만큼 기다렸다면 안 보냈을 비율"을 계산한다.
PAUSE_CANDIDATES_MIN = (1, 2, 3, 5, 10, 15)

# 하루 평균 이 횟수 이상 ALARM으로 진입하면 flapping 후보로 본다.
FLAPPING_PER_DAY = 3

_ALARM_STATES = ("ALARM",)
_CLEAR_STATES = ("OK", "INSUFFICIENT_DATA")


# ──────────────────────────────────────────────
# 순수 로직 (테스트 대상 — backend/tests/test_alarm_history_analysis.py)
# ──────────────────────────────────────────────

def parse_state(history_data: str) -> str:
    """HistoryData(JSON 문자열)에서 새 상태값을 꺼낸다. 파싱 불가면 빈 문자열."""
    try:
        return str(json.loads(history_data).get("newState", {}).get("stateValue", ""))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ""


def build_episodes(transitions: list[tuple[datetime, str]], window_end: datetime) -> list[dict]:
    """상태 전이 목록을 ALARM 에피소드(발화~해소)로 묶는다.

    Args:
        transitions: (시각, 새 상태) 목록. 정렬 여부는 무관 — 내부에서 정렬한다.
        window_end: 조회 창의 끝. 창 끝까지 안 풀린 에피소드의 지속시간 하한으로 쓴다.

    Returns:
        [{"start", "end", "duration_sec", "resolved"}] — `resolved=False`는 창 안에서
        해소를 못 본 경우로, duration은 **하한**이다.

    창 시작 시점에 이미 ALARM이던 경우는 진입 시각을 알 수 없어 제외한다 —
    포함하면 지속시간이 실제보다 짧게 잡혀 유예 효과가 과대평가된다.
    """
    episodes: list[dict] = []
    start: datetime | None = None

    for ts, state in sorted(transitions, key=lambda x: x[0]):
        if state in _ALARM_STATES:
            if start is None:          # 연속 ALARM 재진입은 첫 진입만 센다
                start = ts
        elif state in _CLEAR_STATES and start is not None:
            episodes.append({
                "start": start, "end": ts,
                "duration_sec": (ts - start).total_seconds(), "resolved": True,
            })
            start = None

    if start is not None:
        episodes.append({
            "start": start, "end": None,
            "duration_sec": (window_end - start).total_seconds(), "resolved": False,
        })
    return episodes


def suppression_rate(episodes: list[dict], pause_minutes: float) -> tuple[int, int]:
    """유예 pause_minutes 분을 걸었다면 억제됐을 에피소드 수와 전체 수.

    억제 조건: 유예 시간 안에 **해소된** 에피소드. 미해소(resolved=False)는
    유예를 넘겼다는 뜻이므로 억제되지 않는다.
    """
    if not episodes:
        return 0, 0
    threshold = pause_minutes * 60
    suppressed = sum(1 for e in episodes if e["resolved"] and e["duration_sec"] <= threshold)
    return suppressed, len(episodes)


def percentile(values: list[float], pct: float) -> float:
    """선형 보간 없는 최근접 순위 백분위수 (표본이 적어도 안정적)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def concentration(counter: Counter, top_n: int) -> tuple[int, int, float]:
    """상위 top_n개가 전체에서 차지하는 (건수, 전체, 비율%)."""
    total = sum(counter.values())
    if total == 0:
        return 0, 0, 0.0
    top = sum(c for _k, c in counter.most_common(top_n))
    return top, total, top / total * 100


def recommend_pause(pause_results: dict[int, tuple[int, int]], keep: float = 0.9) -> int:
    """억제 효과의 대부분을 확보하는 **가장 짧은** 유예를 고른다.

    억제율은 유예 시간에 대해 단조 증가하므로 "억제율 최대"를 고르면 언제나 후보 중
    가장 긴 값이 나온다. 그러나 유예는 곧 탐지 지연이므로 길수록 손해다.
    따라서 달성 가능한 최대 억제율의 `keep` 배(기본 90%)에 도달하는 최소 유예를 택한다.

    예: 1분 40% / 2분 55% / 5분 58% / 15분 60% → 최대 60%의 90%인 54%를 넘는 최소값 = 2분
    """
    rates = {
        m: (sup / total if total else 0.0) for m, (sup, total) in pause_results.items()
    }
    if not rates:
        return 0
    best_rate = max(rates.values())
    if best_rate <= 0:
        return min(rates)
    target = best_rate * keep
    return min((m for m, r in sorted(rates.items()) if r >= target), default=min(rates))


def humanize(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}초"
    if seconds < 3600:
        return f"{seconds / 60:.1f}분"
    return f"{seconds / 3600:.1f}시간"


# ──────────────────────────────────────────────
# AWS 수집
# ──────────────────────────────────────────────

def make_session(role_arn: str, region: str):
    if not role_arn:
        return boto3.Session(region_name=region)
    sts = boto3.client("sts")
    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="AlarmHistoryAnalysis")["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def fetch_alarm_metadata(cw) -> dict[str, dict]:
    """알람 이름 → {metric, namespace, threshold, severity}. 이력에는 메트릭이 없어 따로 받는다."""
    meta: dict[str, dict] = {}
    try:
        for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["MetricAlarm"]):
            for alarm in page.get("MetricAlarms", []):
                meta[alarm["AlarmName"]] = {
                    "metric": alarm.get("MetricName", ""),
                    "namespace": alarm.get("Namespace", ""),
                    "threshold": alarm.get("Threshold"),
                    "arn": alarm.get("AlarmArn", ""),
                }
    except ClientError as e:
        print(f"  ! describe_alarms 실패 (메트릭 정보 없이 진행): {e}", file=sys.stderr)
    return meta


def fetch_history(cw, start: datetime, end: datetime) -> list[dict]:
    """조회 창의 상태 전이 이력 전량. 알람 이름을 지정하지 않으면 계정·리전 전체가 나온다."""
    items: list[dict] = []
    paginator = cw.get_paginator("describe_alarm_history")
    kwargs = {
        "HistoryItemType": "StateUpdate",
        "StartDate": start,
        "EndDate": end,
        "AlarmTypes": ["MetricAlarm"],
    }
    try:
        for page in paginator.paginate(**kwargs):
            items.extend(page.get("AlarmHistoryItems", []))
    except ClientError as e:
        print(f"  ! describe_alarm_history 실패: {e}", file=sys.stderr)
    return items


# ──────────────────────────────────────────────
# 분석
# ──────────────────────────────────────────────

def analyze(items: list[dict], meta: dict[str, dict], start: datetime, end: datetime) -> dict:
    by_alarm: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for it in items:
        state = parse_state(it.get("HistoryData", ""))
        if state:
            by_alarm[it["AlarmName"]].append((it["Timestamp"], state))

    episodes_by_alarm = {
        name: build_episodes(trans, end) for name, trans in by_alarm.items()
    }
    all_episodes = [e for eps in episodes_by_alarm.values() for e in eps]

    fires = Counter({name: len(eps) for name, eps in episodes_by_alarm.items() if eps})
    by_metric: Counter = Counter()
    by_namespace: Counter = Counter()
    for name, eps in episodes_by_alarm.items():
        m = meta.get(name, {})
        by_metric[m.get("metric") or "(unknown)"] += len(eps)
        by_namespace[m.get("namespace") or "(unknown)"] += len(eps)

    by_hour: Counter = Counter()
    for e in all_episodes:
        by_hour[e["start"].astimezone(timezone.utc).hour] += 1

    days = max((end - start).total_seconds() / 86400, 1e-9)
    flapping = {
        name: len(eps) / days
        for name, eps in episodes_by_alarm.items()
        if len(eps) / days >= FLAPPING_PER_DAY
    }

    resolved = [e["duration_sec"] for e in all_episodes if e["resolved"]]
    return {
        "window_start": start, "window_end": end, "days": days,
        "raw_transitions": len(items),
        "alarms_with_activity": len(fires),
        "episodes": len(all_episodes),
        "episodes_per_day": len(all_episodes) / days,
        "unresolved": sum(1 for e in all_episodes if not e["resolved"]),
        "durations_resolved": resolved,
        "pause": {
            m: suppression_rate(all_episodes, m) for m in PAUSE_CANDIDATES_MIN
        },
        "fires": fires, "by_metric": by_metric, "by_namespace": by_namespace,
        "by_hour": by_hour, "flapping": flapping, "meta": meta,
    }


def render(a: dict, account: str, region: str) -> str:
    L: list[str] = []
    w = L.append
    w(f"# 알람 노이즈 실측 — {a['window_start']:%Y-%m-%d} ~ {a['window_end']:%Y-%m-%d}")
    w("")
    w(f"- 대상: 계정 `{account}` / 리전 `{region}`")
    w(f"- 창: {a['days']:.1f}일 · 상태 전이 원본 {a['raw_transitions']:,}건")
    w(f"- 발화 에피소드: **{a['episodes']:,}건** (하루 {a['episodes_per_day']:.0f}건), "
      f"활동한 알람 {a['alarms_with_activity']:,}개")
    w(f"- 창 끝까지 미해소: {a['unresolved']:,}건")
    w("")

    if a["episodes"] == 0:
        w("> ⚠️ 이 창에 발화가 없다. 기간(`--days`)을 늘리거나 실제 알람이 있는 계정/리전을 지정할 것.")
        return "\n".join(L)

    # ── 1. auto-pause 효과 — 이 표가 Phase 1의 기본값을 정한다
    w("## 1. Auto-pause 효과 — 유예 시간별 억제율")
    w("")
    w("> N분 기다렸다가 그 사이 스스로 해소되면 안 보내는 정책(design.md D4)을 과거 데이터에")
    w("> 소급 적용한 결과다. **이 표에서 Phase 1의 유예 기본값을 정한다.**")
    w("")
    w("| 유예 | 억제됨 | 남는 알림 | 억제율 |")
    w("|---:|---:|---:|---:|")
    for minutes, (sup, total) in a["pause"].items():
        w(f"| {minutes}분 | {sup:,} | {total - sup:,} | **{sup / total * 100:.1f}%** |")
    w("")

    d = a["durations_resolved"]
    if d:
        w(f"해소된 에피소드 {len(d):,}건의 지속시간: "
          f"p50 {humanize(percentile(d, 50))} · p75 {humanize(percentile(d, 75))} · "
          f"p90 {humanize(percentile(d, 90))} · p99 {humanize(percentile(d, 99))}")
        w("")

    # ── 2. 집중도
    w("## 2. 집중도 — 어디를 깎으면 얼마가 사라지는가")
    w("")
    for n in (5, 10, 20):
        top, total, pct = concentration(a["fires"], n)
        w(f"- 상위 {n}개 알람 = {top:,} / {total:,}건 (**{pct:.1f}%**)")
    w("")
    w("### 발화 상위 20개 알람")
    w("")
    w("| 건수 | 하루평균 | 알람 |")
    w("|---:|---:|---|")
    for name, cnt in a["fires"].most_common(20):
        w(f"| {cnt:,} | {cnt / a['days']:.1f} | `{name[:90]}` |")
    w("")

    # ── 3. 메트릭·네임스페이스
    w("## 3. 노이즈원 — 메트릭 / 네임스페이스")
    w("")
    w("| 건수 | 메트릭 |")
    w("|---:|---|")
    for metric, cnt in a["by_metric"].most_common(15):
        w(f"| {cnt:,} | {metric} |")
    w("")
    w("| 건수 | 네임스페이스 |")
    w("|---:|---|")
    for ns, cnt in a["by_namespace"].most_common(10):
        w(f"| {cnt:,} | {ns} |")
    w("")

    # ── 4. 시간대
    w("## 4. 시간대 분포 (UTC 기준 발화 시각)")
    w("")
    peak = max(a["by_hour"].values()) if a["by_hour"] else 1
    w("| 시(UTC) | 시(KST) | 건수 | |")
    w("|---:|---:|---:|---|")
    for hour in range(24):
        cnt = a["by_hour"].get(hour, 0)
        bar = "█" * int(cnt / peak * 30) if cnt else ""
        w(f"| {hour:02d} | {(hour + 9) % 24:02d} | {cnt:,} | {bar} |")
    w("")
    w("> 업무 시작 시각에 몰려 있으면 \"정상 부하인데 임계치가 낮아서 우는\" 경우일 수 있다 —")
    w("> Shadow 재보정(`threshold_recalibration.py`)의 대상 후보다.")
    w("")

    # ── 5. flapping
    w(f"## 5. Flapping 후보 (하루 {FLAPPING_PER_DAY}회 이상 발화)")
    w("")
    if a["flapping"]:
        w(f"총 **{len(a['flapping'])}개**. 이들만 격리해도 하루 "
          f"{sum(a['flapping'].values()):.0f}건이 줄어든다.")
        w("")
        w("| 하루평균 | 알람 |")
        w("|---:|---|")
        for name, per_day in sorted(a["flapping"].items(), key=lambda x: -x[1])[:20]:
            w(f"| {per_day:.1f} | `{name[:90]}` |")
    else:
        w("없음.")
    w("")

    # ── 6. 결론
    w("## 6. 다음 결정")
    w("")
    rec = recommend_pause(a["pause"])
    sup, total = a["pause"][rec]
    max_sup, max_total = a["pause"][max(a["pause"])]
    w(f"- **Auto-pause 유예 후보: {rec}분** — 억제율 {sup / total * 100:.1f}% "
      f"(하루 {a['episodes_per_day']:.0f}건 → {(total - sup) / a['days']:.0f}건)")
    w(f"  - 더 기다려도 이득이 적다: {max(a['pause'])}분까지 늘려야 "
      f"{max_sup / max_total * 100:.1f}% — 유예는 곧 탐지 지연이므로 짧은 쪽을 택한다")
    w(f"- 상위 10개 알람 격리 시 추가 {concentration(a['fires'], 10)[2]:.1f}% 감소")
    w("- 위 두 가지를 합친 뒤 남는 양이 사람이 감당 가능한 수준인지로 Phase 1 범위를 정한다")
    w("")
    w("> 산출: `scripts/analyze_alarm_history.py` · 스펙: `docs/specs/alert-pipeline/`")
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser(description="CloudWatch 알람 이력 노이즈 분석 (읽기 전용)")
    p.add_argument("--days", type=int, default=7, help="조회 기간(일). 기본 7")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-northeast-2"))
    p.add_argument("--role-arn", default="", help="크로스 어카운트 조회용 역할 ARN")
    p.add_argument("--output", default="", help="출력 경로. 기본 docs/reports/ALARM-NOISE-{today}.md")
    args = p.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    try:
        session = make_session(args.role_arn, args.region)
        account = session.client("sts").get_caller_identity()["Account"]
    except (ClientError, BotoCoreError) as e:
        print(f"자격증명 오류: {e}", file=sys.stderr)
        return 1

    cw = session.client("cloudwatch")
    print(f"[1/3] 알람 메타데이터 수집 ({account}/{args.region}) ...")
    meta = fetch_alarm_metadata(cw)
    print(f"      알람 {len(meta):,}개")

    print(f"[2/3] 상태 전이 이력 수집 (최근 {args.days}일) ...")
    items = fetch_history(cw, start, end)
    print(f"      전이 {len(items):,}건")

    print("[3/3] 분석 ...")
    result = analyze(items, meta, start, end)
    report = render(result, account, args.region)

    out = Path(args.output) if args.output else (
        Path(__file__).resolve().parents[1] / "docs" / "reports"
        / f"ALARM-NOISE-{end:%Y-%m-%d}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    print(f"\n완료: {out}")
    if result["episodes"]:
        rec = recommend_pause(result["pause"])
        sup, total = result["pause"][rec]
        print(f"  발화 {result['episodes']:,}건 (하루 {result['episodes_per_day']:.0f}건)")
        print(f"  auto-pause 권장 {rec}분 → 억제율 {sup / total * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
