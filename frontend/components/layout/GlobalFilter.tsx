"use client";

import { useGlobalFilter } from "@/hooks/useGlobalFilter";

export function GlobalFilter() {
  const { customerId, accountId, serviceId, setCustomerId, setAccountId, setServiceId } = useGlobalFilter();

  return (
    <div className="flex items-center gap-2">
      <select
        value={customerId}
        onChange={(e) => { setCustomerId(e.target.value); setAccountId(""); setServiceId(""); }}
        className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
      >
        <option value="">전체 고객사</option>
      </select>

      <select
        value={accountId}
        onChange={(e) => { setAccountId(e.target.value); setServiceId(""); }}
        className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
      >
        <option value="">전체 어카운트</option>
      </select>

      <select
        value={serviceId}
        onChange={(e) => setServiceId(e.target.value)}
        className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
      >
        <option value="">전체 서비스</option>
      </select>
    </div>
  );
}
