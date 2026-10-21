"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { Customer, Account } from "@/types/index";

export interface GlobalFilterBarProps {
  /** 서버(GlobalFilterOptions)가 내려주는 고객사 — 백엔드가 이미 볼 수 있는 범위로 걸러 준다 */
  customers: Customer[];
  accounts: Account[];
}

/** 브라우저별 마지막 선택 범위 */
export const GLOBAL_SCOPE_STORAGE_KEY = "global_scope";

interface StoredScope { customer: string; account: string }

function readStoredScope(): StoredScope | null {
  try {
    const raw = localStorage.getItem(GLOBAL_SCOPE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredScope>;
    return { customer: parsed.customer ?? "", account: parsed.account ?? "" };
  } catch {
    return null;
  }
}

function writeStoredScope(scope: StoredScope) {
  try {
    if (scope.customer) {
      localStorage.setItem(GLOBAL_SCOPE_STORAGE_KEY, JSON.stringify(scope));
    } else {
      localStorage.removeItem(GLOBAL_SCOPE_STORAGE_KEY);
    }
  } catch { /* localStorage unavailable */ }
}

/**
 * 고객사·계정 범위를 고르는 유일한 곳. URL(?customer=&account=)이 단일 진실 원천이며
 * 페이지들은 searchParams로 이 값을 받는다. 루트 레이아웃이라 useSearchParams 대신
 * window.location.search를 읽는다.
 */
export function GlobalFilterBar({ customers, accounts }: GlobalFilterBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [queryString, setQueryString] = useState("");

  useEffect(() => {
    setQueryString(window.location.search);
  }, [pathname]);

  // 뒤로/앞으로 이동은 pathname이 같을 수 있어 따로 듣는다
  useEffect(() => {
    const onPop = () => setQueryString(window.location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const searchParams = useMemo(() => new URLSearchParams(queryString), [queryString]);
  const customerId = searchParams.get("customer") ?? "";
  const accountId = searchParams.get("account") ?? "";

  const navigate = useCallback(
    (updates: Record<string, string>, mode: "push" | "replace") => {
      const params = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(updates)) {
        if (value) params.set(key, value);
        else params.delete(key);
      }
      const nextQuery = params.toString();
      setQueryString(nextQuery ? `?${nextQuery}` : "");
      const url = nextQuery ? `${pathname}?${nextQuery}` : pathname;
      if (mode === "push") router.push(url);
      else router.replace(url);
    },
    [router, pathname],
  );

  const isKnownCustomer = useCallback(
    (id: string) => customers.some((c) => c.customer_id === id),
    [customers],
  );
  const isAccountOf = useCallback(
    (id: string, customer: string) =>
      accounts.some((a) => a.account_id === id && a.customer_id === customer),
    [accounts],
  );

  // 로드 시 정합: 범위 밖 고객사는 버리고, URL에 고객사가 없으면 마지막 선택을 복원한다
  useEffect(() => {
    if (customers.length === 0) return;
    const params = new URLSearchParams(window.location.search);
    const urlCustomer = params.get("customer") ?? "";
    // 목록을 못 불러왔으면(빈 목록) 판단하지 않는다 — 멀쩡한 선택을 지우면 안 된다
    if (customers.length === 0) return;
    if (urlCustomer && !isKnownCustomer(urlCustomer)) {
      navigate({ customer: "", account: "" }, "replace");
      return;
    }
    if (urlCustomer) return;
    const stored = readStoredScope();
    if (!stored?.customer || !isKnownCustomer(stored.customer)) return;
    const account = stored.account && isAccountOf(stored.account, stored.customer) ? stored.account : "";
    navigate({ customer: stored.customer, account }, "replace");
    // pathname 변화(=새 페이지 진입)마다 한 번 판단한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, customers, accounts]);

  const handleCustomerChange = (value: string) => {
    writeStoredScope({ customer: value, account: "" });
    navigate({ customer: value, account: "" }, "push");
  };

  const handleAccountChange = (value: string) => {
    writeStoredScope({ customer: customerId, account: value });
    navigate({ account: value }, "push");
  };

  const filteredAccounts = customerId
    ? accounts.filter((a) => a.customer_id === customerId)
    : accounts;

  const selectClass =
    "rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20";

  return (
    <div className="flex items-center gap-3">
      <select
        value={customerId}
        onChange={(e) => handleCustomerChange(e.target.value)}
        className={selectClass}
        aria-label="Customer filter"
      >
        <option value="">전체 고객사</option>
        {customers.map((c) => (
          <option key={c.customer_id} value={c.customer_id}>
            {c.name}
          </option>
        ))}
      </select>

      <select
        value={accountId}
        onChange={(e) => handleAccountChange(e.target.value)}
        className={selectClass}
        aria-label="Account filter"
      >
        <option value="">전체 계정</option>
        {filteredAccounts.map((a) => (
          <option key={a.account_id} value={a.account_id}>
            {a.name}
          </option>
        ))}
      </select>
    </div>
  );
}
