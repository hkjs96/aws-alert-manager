"""유저별 고객사 접근 범위 (docs/specs/authz-scoping/design.md).

관리자(`ADMIN_EMAILS`)는 전부, 일반 사용자는 고객사 `managers`에 자기 이메일이 든 고객사와 그 계정만 본다.
`ADMIN_EMAILS`가 비었으면 제한 없음(`identity.admin_enforced()`와 같은 기준). 설정돼 있는데 이메일이 없으면 아무것도 못 본다.

백엔드가 보안 경계다(프론트 필터는 UX일 뿐). 조회는 범위로 걸러내고, 단건·변경 대상이 범위 밖이면 호출부가 404를 낸다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from api_handler.db import accounts_table, customers_table, scan_all
from api_handler.identity import admin_enforced, current_email, is_admin

logger = logging.getLogger(__name__)


def normalize_managers(value) -> list[str]:
    """이메일 목록 — 소문자·공백 제거·중복 제거, 순서 유지. 리스트가 아니면 []."""
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for v in value:
        e = str(v).strip().lower()
        if e and e not in seen:
            seen.append(e)
    return seen


@dataclass(frozen=True)
class Scope:
    email: str
    unrestricted: bool
    customer_ids: frozenset[str] = field(default_factory=frozenset)
    account_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.unrestricted

    def allows_customer(self, customer_id: str | None) -> bool:
        return self.unrestricted or (bool(customer_id) and customer_id in self.customer_ids)

    def allows_account(self, account_id: str | None) -> bool:
        return self.unrestricted or (bool(account_id) and account_id in self.account_ids)

    def allows_item(self, item: dict) -> bool:
        """`customer_id`가 있으면 그것으로, 없으면 `account_id`로. 둘 다 없으면 관리자만(고객사 없는 데이터)."""
        if self.unrestricted:
            return True
        cid = item.get("customer_id")
        if cid:
            return cid in self.customer_ids
        return self.allows_account(item.get("account_id") or item.get("account"))

    def filter(self, items):
        return items if self.unrestricted else [i for i in items if self.allows_item(i)]


def scope_for(event: dict) -> Scope:
    email = current_email(event)
    if not admin_enforced() or is_admin(email):
        return Scope(email=email, unrestricted=True)
    if not email:
        # 관리자 설정이 있는데 신원이 없다 — 인증이 켜져 있으면 생길 수 없는 경우라, 생기면 닫는 쪽으로 실패한다.
        return Scope(email=email, unrestricted=False)
    try:
        customers = scan_all(customers_table())
        accounts = scan_all(accounts_table())
    except (ClientError, KeyError) as e:   # KeyError: 표 이름 환경 변수가 없는 구성
        # 범위를 못 정하면 아무것도 보이지 않게 한다(열어 두지 않는다).
        logger.error("Scope lookup failed for %s: %s", email, e)
        return Scope(email=email, unrestricted=False)
    cids = frozenset(c["customer_id"] for c in customers if email in normalize_managers(c.get("managers")))
    aids = frozenset(a["account_id"] for a in accounts if a.get("customer_id") in cids and a.get("account_id"))
    return Scope(email=email, unrestricted=False, customer_ids=cids, account_ids=aids)
