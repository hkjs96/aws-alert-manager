"use client";

import { RESOURCE_TYPE_CATEGORIES, type ResourceType } from "@/lib/constants";

interface FilterBarProps {
  customers: { id: string; name: string }[];
  accounts: { id: string; name: string }[];
  selectedCustomer: string;
  selectedAccount: string;
  selectedResourceType: string;
  monitoringFilter: "all" | "on" | "off";
  searchQuery: string;
  onCustomerChange: (id: string) => void;
  onAccountChange: (id: string) => void;
  onResourceTypeChange: (type: string) => void;
  onMonitoringFilterChange: (filter: "all" | "on" | "off") => void;
  onSearchChange: (query: string) => void;
}

export function FilterBar({
  customers,
  accounts,
  selectedCustomer,
  selectedAccount,
  selectedResourceType,
  monitoringFilter,
  searchQuery,
  onCustomerChange,
  onAccountChange,
  onResourceTypeChange,
  onMonitoringFilterChange,
  onSearchChange,
}: FilterBarProps) {
  return (
    <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedCustomer}
          onChange={(e) => onCustomerChange(e.target.value)}
          className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
        >
          <option value="">전체 고객사</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          value={selectedAccount}
          onChange={(e) => onAccountChange(e.target.value)}
          className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
        >
          <option value="">전체 어카운트</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>

        <select
          value={selectedResourceType}
          onChange={(e) => onResourceTypeChange(e.target.value)}
          className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
        >
          <option value="">전체 리소스 유형</option>
          {Object.entries(RESOURCE_TYPE_CATEGORIES).map(([category, types]) => (
            <optgroup key={category} label={category}>
              {types.map((t: ResourceType) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </optgroup>
          ))}
        </select>

        <div className="flex rounded-md border border-slate-200">
          {(["all", "on", "off"] as const).map((f) => (
            <button
              key={f}
              onClick={() => onMonitoringFilterChange(f)}
              className={`px-3 py-1.5 text-sm ${
                monitoringFilter === f
                  ? "bg-accent text-white"
                  : "text-slate-600 hover:bg-slate-50"
              } ${f === "all" ? "rounded-l-md" : f === "off" ? "rounded-r-md" : ""}`}
            >
              {f === "all" ? "전체" : f === "on" ? "ON" : "OFF"}
            </button>
          ))}
        </div>

        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="리소스 ID 또는 이름 검색..."
          className="rounded-md border border-slate-200 px-3 py-1.5 text-sm placeholder:text-slate-400"
        />
      </div>
    </div>
  );
}
