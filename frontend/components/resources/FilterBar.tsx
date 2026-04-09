"use client";

import { Search } from "lucide-react";

const RESOURCE_TYPES = ["EC2", "S3", "RDS", "LAMBDA", "ALB"] as const;

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
}: FilterBarProps) {
  return (
    <section className="bg-slate-100 rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
      {/* Customer */}
      <div className="space-y-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">
          Customer
        </label>
        <select
          value={customerFilter}
          onChange={(e) => onCustomerChange(e.target.value)}
          className="w-full bg-white border-none rounded-lg text-sm px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary/20 outline-none"
        >
          <option value="">All Customers</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {/* Account — filtered by selected customer */}
      <div className="space-y-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">
          Account
        </label>
        <select
          value={accountFilter}
          onChange={(e) => onAccountChange(e.target.value)}
          className="w-full bg-white border-none rounded-lg text-sm px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary/20 outline-none"
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
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">
          Resource Type
        </label>
        <select
          value={typeFilter}
          onChange={(e) => onTypeChange(e.target.value)}
          className="w-full bg-white border-none rounded-lg text-sm px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary/20 outline-none"
        >
          <option value="">All Types</option>
          {RESOURCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Quick Search */}
      <div className="space-y-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">
          Quick Search
        </label>
        <div className="relative">
          <Search className="absolute left-2 top-1.5 text-slate-400" size={16} />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full bg-white border-none rounded-lg text-sm pl-8 pr-3 py-2 shadow-sm focus:ring-2 focus:ring-primary/20 outline-none"
            placeholder="Resource ID or Name..."
          />
        </div>
      </div>
    </section>
  );
}
