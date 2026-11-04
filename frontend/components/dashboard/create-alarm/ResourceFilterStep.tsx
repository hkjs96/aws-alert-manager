"use client";

import { useEffect, useState } from "react";
import { filterAccounts, filterResources, type Track } from "@/lib/alarm-modal-utils";
import { fetchCustomers, fetchAccounts } from "@/lib/api-functions";
import type { Customer, Account, Resource } from "@/types";

interface ResourceFilterStepProps {
  track: Track;
  customerId: string;
  accountId: string;
  resourceId: string;
  allResources: Resource[];  // 부모 CreateAlarmModal에서 주입 (중복 페치 방지)
  onCustomerChange: (id: string) => void;
  onAccountChange: (id: string) => void;
  onResourceChange: (id: string) => void;
}

export function ResourceFilterStep({
  track, customerId, accountId, resourceId,
  allResources,
  onCustomerChange, onAccountChange, onResourceChange,
}: ResourceFilterStepProps) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [allAccounts, setAllAccounts] = useState<Account[]>([]);

  useEffect(() => {
    void Promise.all([fetchCustomers(), fetchAccounts()])
      .then(([c, a]) => {
        setCustomers(c);
        setAllAccounts(a);
      })
      .catch(() => {});
  }, []);

  const accounts = customerId ? filterAccounts(allAccounts, customerId) : [];
  const resources = accountId ? filterResources(allResources, accountId, track) : [];

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-700">Select Resource</h3>

      {/* 고객사 */}
      <div>
        <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">Customer</label>
        <select
          data-testid="customer-select"
          value={customerId}
          onChange={(e) => onCustomerChange(e.target.value)}
          className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none"
        >
          <option value="">Select a customer...</option>
          {customers.map((c) => (
            <option key={c.customer_id} value={c.customer_id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* 어카운트 */}
      <div>
        <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">Account</label>
        <select
          data-testid="account-select"
          value={accountId}
          onChange={(e) => onAccountChange(e.target.value)}
          disabled={!customerId}
          className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none disabled:bg-slate-50 disabled:text-slate-300"
        >
          <option value="">Select an account...</option>
          {accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>{a.name} ({a.account_id})</option>
          ))}
        </select>
        {customerId && accounts.length === 0 && (
          <p className="mt-1 text-xs text-slate-400">No accounts</p>
        )}
      </div>

      {/* 리소스 */}
      <div>
        <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">Resource</label>
        <select
          data-testid="resource-select"
          value={resourceId}
          onChange={(e) => onResourceChange(e.target.value)}
          disabled={!accountId}
          className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none disabled:bg-slate-50 disabled:text-slate-300"
        >
          <option value="">Select a resource...</option>
          {resources.map((r) => (
            <option key={r.id} value={r.id}>{r.name} ({r.type})</option>
          ))}
        </select>
        {accountId && resources.length === 0 && (
          <p className="mt-1 text-xs text-slate-400">
            {track === 1 ? "No monitored resources" : "No unmonitored resources"}
          </p>
        )}
      </div>
    </div>
  );
}
