"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { Customer, Account } from "@/types/index";
import { fetchCustomers, fetchAccounts } from "@/lib/api-functions";
import { useOwnedCustomers } from "@/hooks/useOwnedCustomers";
import { FRONTEND_INTEGRATION_RESOURCE_TYPES } from "@/lib/constants";

function GlobalFilterBarInner() {
  const router = useRouter();
  const pathname = usePathname();
  const { ownedCustomerIds } = useOwnedCustomers();

  const [allCustomers, setAllCustomers] = useState<Customer[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [queryString, setQueryString] = useState("");

  useEffect(() => {
    setQueryString(window.location.search);
  }, [pathname]);

  const searchParams = useMemo(
    () => new URLSearchParams(queryString),
    [queryString],
  );

  const customerId = searchParams.get("customer_id") ?? "";
  const accountId = searchParams.get("account_id") ?? "";
  const service = searchParams.get("service") ?? "";

  // 담당 고객사만 드롭다운에 표시
  const customers = allCustomers.filter((c) =>
    ownedCustomerIds.includes(c.customer_id),
  );

  useEffect(() => {
    Promise.all([fetchCustomers(), fetchAccounts()])
      .then(([c, a]) => {
        setAllCustomers(c);
        setAccounts(a);
      })
      .catch(() => {
        // 에러 시 빈 목록 유지
      });
  }, []);

  // URL에 비담당 customer_id가 있으면 조용히 제거
  useEffect(() => {
    if (
      customerId &&
      ownedCustomerIds.length > 0 &&
      !ownedCustomerIds.includes(customerId)
    ) {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("customer_id");
      params.delete("account_id");
      params.delete("service");
      const nextQuery = params.toString();
      setQueryString(nextQuery ? `?${nextQuery}` : "");
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname);
    }
  }, [customerId, ownedCustomerIds, searchParams, pathname, router]);

  const updateParams = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value) {
          params.set(key, value);
        } else {
          params.delete(key);
        }
      }
      const nextQuery = params.toString();
      setQueryString(nextQuery ? `?${nextQuery}` : "");
      router.push(nextQuery ? `${pathname}?${nextQuery}` : pathname);
    },
    [router, pathname, searchParams],
  );

  const handleCustomerChange = useCallback(
    (value: string) => {
      updateParams({ customer_id: value, account_id: "", service: "" });
    },
    [updateParams],
  );

  const handleAccountChange = useCallback(
    (value: string) => {
      updateParams({ account_id: value, service: "" });
    },
    [updateParams],
  );

  const handleServiceChange = useCallback(
    (value: string) => {
      updateParams({ service: value });
    },
    [updateParams],
  );

  const filteredAccounts = customerId
    ? accounts.filter((a) => a.customer_id === customerId)
    : accounts;

  const noOwnedCustomers = ownedCustomerIds.length === 0;

  return (
    <div className="flex items-center gap-3">
      <select
        value={customerId}
        onChange={(e) => handleCustomerChange(e.target.value)}
        disabled={noOwnedCustomers}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50 disabled:cursor-not-allowed"
        aria-label="Customer filter"
      >
        {noOwnedCustomers ? (
          <option value="">담당 고객사 없음</option>
        ) : (
          <>
            <option value="">All Customers</option>
            {customers.map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.name}
              </option>
            ))}
          </>
        )}
      </select>

      <select
        value={accountId}
        onChange={(e) => handleAccountChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20"
        aria-label="Account filter"
      >
        <option value="">All Accounts</option>
        {filteredAccounts.map((a) => (
          <option key={a.account_id} value={a.account_id}>
            {a.name}
          </option>
        ))}
      </select>

      <select
        value={service}
        onChange={(e) => handleServiceChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20"
        aria-label="Service filter"
      >
        <option value="">All Services</option>
        {FRONTEND_INTEGRATION_RESOURCE_TYPES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}

export function GlobalFilterBar() {
  return <GlobalFilterBarInner />;
}
