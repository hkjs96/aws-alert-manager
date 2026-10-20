#!/usr/bin/env python3
"""고객사 담당자 이전 — 사용자 설정의 `owned_customer_ids`(개인 화면 필터)를 고객사 `managers`(접근 권한)로 옮긴다.

docs/specs/authz-scoping/design.md. 권한이 켜지는 순간 담당자가 없는 고객사는 일반 사용자에게 안 보이므로, 배포 전에 돌린다.
기존 `managers`는 지우지 않고 합친다(여러 번 돌려도 같다). 기본은 드라이런 — `--apply`로 쓴다.

    python scripts/migrate_customer_managers.py --env dev            # 계획만
    python scripts/migrate_customer_managers.py --env dev --apply    # 반영
"""

from __future__ import annotations

import argparse
import sys


def plan(customers: list[dict], prefs: list[dict]) -> dict[str, list[str]]:
    """customer_id → 합친 managers(기존 + 그 고객사를 담당으로 체크한 사용자). 바뀌는 고객사만."""
    wanted: dict[str, list[str]] = {}
    for p in prefs:
        email = str(p.get("user_email", "")).strip().lower()
        for cid in p.get("owned_customer_ids") or []:
            if email:
                wanted.setdefault(cid, []).append(email)
    changes: dict[str, list[str]] = {}
    for c in customers:
        cid = c["customer_id"]
        current = [str(e).strip().lower() for e in (c.get("managers") or [])]
        merged = list(dict.fromkeys([*current, *wanted.get(cid, [])]))
        if merged != current:
            changes[cid] = merged
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="dev")
    ap.add_argument("--profile", default="tlsgks678_poc")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import boto3
    ddb = boto3.session.Session(profile_name=args.profile, region_name=args.region).resource("dynamodb")
    customers_t = ddb.Table(f"aws-monitoring-customers-{args.env}")
    customers = customers_t.scan()["Items"]
    prefs = ddb.Table(f"aws-monitoring-user-prefs-{args.env}").scan()["Items"]

    changes = plan(customers, prefs)
    no_manager = [c["customer_id"] for c in customers if c["customer_id"] not in changes and not c.get("managers")]
    for cid, managers in changes.items():
        print(f"{'APPLY' if args.apply else 'PLAN '} {cid}: managers = {managers}")
        if args.apply:
            customers_t.update_item(Key={"customer_id": cid}, UpdateExpression="SET managers = :m",
                                    ExpressionAttributeValues={":m": managers})
    for cid in no_manager:
        print(f"WARN  {cid}: no managers — only admins will see it")
    if not changes:
        print("nothing to change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
