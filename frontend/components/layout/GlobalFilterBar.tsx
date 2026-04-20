"use client";

import { useCallback, useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import type { Customer, Account } from "@/types/index";
import { fetchCustomers, fetchAccounts } from "@/lib/api-functions";

const SERVICES = ["EC2", "RDS", "S3", "LAMBDA", "ALB"] as const;

function GlobalFilterBarInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);

  const customerId = searchParams.get("customer_id") ?? "";
  const accountId = searchParams.get("account_id") ?? "";
  const service = searchParams.get("service") ?? "";

  useEffect(() => {
    Promise.all([fetchCustomers(), fetchAccounts()])
      .then(([c, a]) => {
        setCustomers(c);
        setAccounts(a);
      })
      .catch(() => {
        // 에러 시 빈 목록 유지
      });
  }, []);

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
      router.push(`${pathname}?${params.toString()}`);
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

  return (
    <div className="flex items-center gap-3">
      <select
        value={customerId}
        onChange={(e) => handleCustomerChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20"
        aria-label="Customer filter"
      >
        <option value="">All Customers</option>
        {customers.map((c) => (
          <option key={c.customer_id} value={c.customer_id}>
            {c.name}
          </option>
        ))}
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
        {SERVICES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}

export function GlobalFilterBar() {
  return (
    <Suspense fallback={<div className="flex items-center gap-3 text-sm text-slate-400">Loading filters...</div>}>
      <GlobalFilterBarInner />
    </Suspense>
  );
}
