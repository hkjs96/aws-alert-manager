"use client";

import { Search } from "lucide-react";

interface FilterBarProps {
  search: string;
  onSearchChange: (v: string) => void;
}

export function FilterBar({ search, onSearchChange }: FilterBarProps) {
  return (
    <section className="bg-slate-100 rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
      {[
        { label: "Customer", options: ["All Customers", "Acme Corp", "Global Dynamics"] },
        { label: "Account", options: ["All Accounts", "Prod-01", "Staging-B"] },
        { label: "Resource Type", options: ["EC2 Instances", "Lambda Functions", "RDS Clusters"] },
      ].map((f, i) => (
        <div key={i} className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">
            {f.label}
          </label>
          <select className="w-full bg-white border-none rounded-lg text-sm px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary/20 outline-none">
            {f.options.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>
      ))}
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
