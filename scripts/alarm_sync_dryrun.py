#!/usr/bin/env python3
"""
alarm-sync 드라이런 — "지금 daily run이 돌면 어떤 알람이 만들어지는가"를 **쓰지 않고** 덤프한다.

리소스 타입 레지스트리 이관(docs/specs/resource-type-registry P2·P3)의 게이트다: 이관 전후 덤프를
비교해 알람 이름·차원·임계치 집합이 0 diff여야 한다. 알람 이름이 곧 리소스의 정체이므로 이것이
회귀의 정의다(요구사항 R5).

이름·차원 계산을 여기서 다시 흉내 내지 않는다. **진짜 생성 경로**(`create_alarms_for_resource`)를 그대로
돌리되, CloudWatch 클라이언트를 쓰기 호출만 가로채는 스텁으로 바꿔 끼운다 — `put_metric_alarm`·
`tag_resource`·`delete_alarms`·`untag_resource`는 기록만 하고, `list_metrics`·`describe_alarms` 같은 읽기는
실제 클라이언트에 위임한다. 그래서 디스크 경로 발견·동적 알람·등급 태그까지 실제와 같은 payload가 나온다.

사용:
    AWS_PROFILE=tlsgks678_poc python scripts/alarm_sync_dryrun.py --region us-east-1 \\
        --output docs/reports/alarm-dryrun-dev-2026-09-15.json
    # 비교
    python scripts/alarm_sync_dryrun.py --diff before.json after.json

읽기 전용이다: 수집기(describe_*/RGT)와 CloudWatch 읽기 API만 부른다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

#: 가로채는 쓰기 호출. 이 밖의 메서드는 실제 클라이언트로 간다.
WRITE_OPS = {"put_metric_alarm", "delete_alarms", "tag_resource", "untag_resource",
             "set_alarm_state", "put_composite_alarm", "disable_alarm_actions", "enable_alarm_actions"}

#: 덤프에 남기는 put_metric_alarm 필드 — 이름·정체·판정 조건. AlarmActions(SNS ARN)는 환경마다 달라 뺀다.
KEEP = ("AlarmName", "Namespace", "MetricName", "Dimensions", "Statistic", "ExtendedStatistic", "Period",
        "EvaluationPeriods", "DatapointsToAlarm", "Threshold", "ComparisonOperator", "TreatMissingData",
        "Metrics")


class RecordingCloudWatch:
    """쓰기만 기록하는 CloudWatch. 읽기는 실제 클라이언트에 위임한다."""

    def __init__(self, real):
        self._real = real
        self.puts: list[dict] = []
        self.deletes: list[list[str]] = []
        self.tags: list[dict] = []

    def put_metric_alarm(self, **kw):
        self.puts.append(kw)
        return {}

    def put_composite_alarm(self, **kw):
        self.puts.append(kw)
        return {}

    def delete_alarms(self, AlarmNames=(), **_):
        self.deletes.append(list(AlarmNames))
        return {}

    def tag_resource(self, **kw):
        self.tags.append(kw)
        return {}

    def untag_resource(self, **kw):
        return {}

    def set_alarm_state(self, **kw):
        return {}

    def disable_alarm_actions(self, **kw):
        return {}

    def enable_alarm_actions(self, **kw):
        return {}

    def __getattr__(self, name):
        if name in WRITE_OPS:
            raise AssertionError(f"write op {name} must be stubbed explicitly")
        return getattr(self._real, name)


def _collect(region: str) -> list[dict]:
    """daily_monitor와 같은 수집기 목록·태그 캐시로 감시 대상 리소스를 모은다(읽기 전용)."""
    import boto3
    from botocore.exceptions import ClientError
    from daily_monitor import lambda_handler as dm

    account = boto3.client("sts").get_caller_identity()["Account"]
    try:
        dm._prime_tag_cache(account)
    except Exception as e:                                       # noqa: BLE001 — 캐시는 최적화일 뿐
        print(f"[dryrun] tag cache not primed ({e}); collectors fall back to per-resource tag calls")
    resources: list[dict] = []
    for mod in dm._COLLECTOR_MODULES:
        try:
            found = mod.collect_monitored_resources()
        except ClientError as e:
            print(f"[dryrun] {mod.__name__}: {e.response['Error']['Code']} — skipped")
            continue
        for r in found:
            resources.append({"type": r["type"], "id": r["id"], "region": r.get("region") or region,
                              "tags": dict(r.get("tags") or {})})
    return resources


def _plan(resource: dict) -> dict:
    """리소스 하나에 대해 실제 생성 경로를 스텁 위에서 돌려 payload를 받는다."""
    import common._clients as clients
    from common.alarm_manager import create_alarms_for_resource
    from common.alarm_registry import _GLOBAL_SERVICE_REGION

    rtype, rid, tags = resource["type"], resource["id"], resource["tags"]
    global_region = _GLOBAL_SERVICE_REGION.get(rtype)
    real = clients._get_cw_client_for_region(global_region) if global_region else clients._get_cw_client()
    cw = RecordingCloudWatch(real)
    # severity_overrides={} — 재생성 시 기존 태그를 읽는 경로를 건너뛴다(드라이런은 "새로 만들면"을 본다)
    created = create_alarms_for_resource(rid, rtype, tags, cw=cw, severity_overrides={})
    alarms = []
    for kw in cw.puts:
        entry = {k: kw[k] for k in KEEP if k in kw}
        if "Dimensions" in entry:
            entry["Dimensions"] = sorted(entry["Dimensions"], key=lambda d: d["Name"])
        alarms.append(entry)
    alarms.sort(key=lambda a: a.get("AlarmName", ""))
    return {
        "type": rtype, "id": rid, "region": resource["region"],
        "name": tags.get("Name", ""),
        "internal_tags": {k: v for k, v in sorted(tags.items()) if k.startswith("_")},
        "threshold_tags": {k: v for k, v in sorted(tags.items()) if k.startswith("Threshold_")},
        "created_names": sorted(created),
        "alarms": alarms,
    }


def run(region: str, output: Path) -> dict:
    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)
    resources = _collect(region)
    print(f"[dryrun] {len(resources)} monitored resources from collectors")
    plans = []
    for r in sorted(resources, key=lambda x: (x["type"], x["id"])):
        try:
            plans.append(_plan(r))
        except Exception as e:                                   # noqa: BLE001 — 한 리소스가 전체를 막지 않는다
            plans.append({"type": r["type"], "id": r["id"], "region": r["region"], "error": f"{type(e).__name__}: {e}"})
            print(f"[dryrun] {r['type']} {r['id']}: {type(e).__name__}: {e}")
    by_type = Counter(p["type"] for p in plans)
    alarm_count = sum(len(p.get("alarms", [])) for p in plans)
    out = {"_meta": {"region": region, "resources": len(plans), "alarms": alarm_count,
                     "by_type": dict(sorted(by_type.items()))},
           "resources": plans}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"[dryrun] {alarm_count} alarms planned for {len(plans)} resources → {output}")
    return out


def diff(before: Path, after: Path) -> int:
    a = json.loads(before.read_text(encoding="utf-8"))
    b = json.loads(after.read_text(encoding="utf-8"))

    def index(doc):
        out = {}
        for r in doc["resources"]:
            for al in r.get("alarms", []):
                out[al.get("AlarmName", "")] = json.dumps(al, sort_keys=True, ensure_ascii=False, default=str)
        return out

    ia, ib = index(a), index(b)
    only_a, only_b = sorted(set(ia) - set(ib)), sorted(set(ib) - set(ia))
    changed = sorted(n for n in set(ia) & set(ib) if ia[n] != ib[n])
    print(f"before {len(ia)} alarms / after {len(ib)} alarms")
    for label, names in (("only before", only_a), ("only after", only_b), ("changed", changed)):
        print(f"  {label}: {len(names)}")
        for n in names[:20]:
            print(f"    {n}")
    return 0 if not (only_a or only_b or changed) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--output", default="")
    p.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = p.parse_args()
    if args.diff:
        return diff(Path(args.diff[0]), Path(args.diff[1]))
    from datetime import date
    output = Path(args.output) if args.output else ROOT / "docs" / "reports" / f"alarm-dryrun-{date.today().isoformat()}.json"
    run(args.region, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
