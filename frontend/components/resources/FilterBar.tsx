"use client";

import { Search } from "lucide-react";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

interface FilterBarProps {
  search: string;
  onSearchChange: (v: string) => void;
  customerFilter: string;
  onCustomerChange: (v: string) => void;
  accountFilter: string;
  onAccountChange: (v: string) => void;
  typeFilter: string;
  onTypeChange: (v: string) => void;
  customers: { id: string; name: string }[];
  accounts: { id: string; name: string }[];
  hideSearch?: boolean;
  onClearAll?: () => void;
}

export function FilterBar({
  search,
  onSearchChange,
  customerFilter,
  onCustomerChange,
  accountFilter,
  onAccountChange,
  typeFilter,
  onTypeChange,
  customers,
  accounts,
  hideSearch,
  onClearAll,
}: FilterBarProps) {
  const gridCols = hideSearch ? "grid-cols-1 md:grid-cols-3" : "grid-cols-1 md:grid-cols-4";

  const activeCount = [
    customerFilter !== "",
    accountFilter !== "",
    typeFilter !== "",
    !hideSearch && search !== "",
  ].filter(Boolean).length;

  return (
    <section className="bg-white/80 backdrop-blur rounded-xl p-4 border border-slate-200 shadow-sm">
      <div className={`grid ${gridCols} gap-4 items-center`}>
        {/* Customer */}
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1 inline-flex items-center gap-1.5">
            Customer
            {customerFilter && (
              <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
            )}
          </label>
          <select
            value={customerFilter}
            onChange={(e) => onCustomerChange(e.target.value)}
            className="w-full bg-slate-50 border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors"
          >
            <option value="">All Customers</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        {/* Account */}
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1 inline-flex items-center gap-1.5">
            Account
            {accountFilter && (
              <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
            )}
          </label>
          <select
            value={accountFilter}
            onChange={(e) => onAccountChange(e.target.value)}
            className="w-full bg-slate-50 border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors"
          >
            <option value="">All Accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        {/* Resource Type */}
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1 inline-flex items-center gap-1.5">
            Resource Type
            {typeFilter && (
              <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
            )}
          </label>
          <select
            value={typeFilter}
            onChange={(e) => onTypeChange(e.target.value)}
            className="w-full bg-slate-50 border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors"
          >
            <option value="">All Types</option>
            {SUPPORTED_RESOURCE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Quick Search */}
        {!hideSearch && (
          <div className="space-y-1">
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1 inline-flex items-center gap-1.5">
              Quick Search
              {search && (
                <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
              )}
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
              <input
                type="text"
                value={search}
                onChange={(e) => onSearchChange(e.target.value)}
                className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
                placeholder="Resource or Metric..."
              />
            </div>
          </div>
        )}
      </div>

      {activeCount > 0 && onClearAll && (
        <div className="mt-3 flex justify-end border-t border-slate-100 pt-2">
          <button
            onClick={onClearAll}
            className="text-xs font-semibold text-primary hover:underline"
          >
            Clear all ({activeCount})
          </button>
        </div>
      )}
    </section>
  );
}
