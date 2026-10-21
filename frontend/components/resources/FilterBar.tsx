"use client";

import { Search } from "lucide-react";
import { FRONTEND_INTEGRATION_RESOURCE_TYPES } from "@/lib/constants";

interface FilterBarProps {
  search: string;
  onSearchChange: (v: string) => void;
  typeFilter: string;
  onTypeChange: (v: string) => void;
  hideSearch?: boolean;
  onClearAll?: () => void;
}

export function FilterBar({
  search,
  onSearchChange,
  typeFilter,
  onTypeChange,
  hideSearch,
  onClearAll,
}: FilterBarProps) {
  const gridCols = hideSearch ? "grid-cols-1" : "grid-cols-1 md:grid-cols-2";

  const activeCount = [
    typeFilter !== "",
    !hideSearch && search !== "",
  ].filter(Boolean).length;

  return (
    <section className="bg-white/80 backdrop-blur rounded-xl p-4 border border-slate-200 shadow-sm">
      <div className={`grid ${gridCols} gap-4 items-center`}>
        {/* 고객사·계정은 상단 글로벌 필터에서만 고른다 */}
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
            {FRONTEND_INTEGRATION_RESOURCE_TYPES.map((t) => (
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
