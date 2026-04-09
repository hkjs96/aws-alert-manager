"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Download } from "lucide-react";
import type { Alarm } from "@/types";
import type { AlarmSummary, AlarmStateFilter } from "@/types/api";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { Pagination } from "@/components/shared/Pagination";
import { downloadCsv } from "@/lib/exportCsv";
import { AlarmSummaryCards } from "./AlarmSummaryCards";
import { AlarmTable } from "./AlarmTable";

const FILTER_TABS: AlarmStateFilter[] = ["ALL", "ALARM", "INSUFFICIENT", "OK", "OFF"];

interface AlarmsContentProps {
  alarms: Alarm[];
  summary: AlarmSummary;
  total: number;
  page: number;
  pageSize: number;
  currentFilter: AlarmStateFilter;
  currentSearch: string;
}

export function AlarmsContent({
  alarms,
  summary,
  total,
  page,
  pageSize,
  currentFilter,
  currentSearch,
}: AlarmsContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const [search, setSearch] = useState(currentSearch);
  const [isExporting, setIsExporting] = useState(false);

  const pushParams = (overrides: Record<string, string>) => {
    const params = new URLSearchParams();
    const merged = {
      state: currentFilter,
      search: currentSearch,
      page: String(page),
      page_size: String(pageSize),
      ...overrides,
    };
    for (const [k, v] of Object.entries(merged)) {
      if (v && v !== "ALL" && v !== "1" && !(k === "page_size" && v === "25")) {
        params.set(k, v);
      }
    }
    // Always keep explicit state if not ALL
    if (merged.state && merged.state !== "ALL") params.set("state", merged.state);
    router.push(`/alarms?${params.toString()}`);
  };

  const handleFilterChange = (f: AlarmStateFilter) => {
    pushParams({ state: f, page: "1" });
  };

  const handleSearchSubmit = () => {
    pushParams({ search, page: "1" });
  };

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const filters: Record<string, string | undefined> = {};
      if (currentFilter !== "ALL") filters.state = currentFilter;
      if (currentSearch) filters.search = currentSearch;
      await downloadCsv("/api/alarms/export", filters, "alarms");
      showToast("success", "CSV 내보내기가 완료되었습니다.");
    } catch {
      showToast("error", "CSV 내보내기에 실패했습니다.");
    } finally {
      setIsExporting(false);
    }
  };

  const handlePageChange = (newPage: number) => {
    pushParams({ page: String(newPage) });
  };

  const handlePageSizeChange = (newSize: number) => {
    pushParams({ page: "1", page_size: String(newSize) });
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
            Active Alarms
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Comprehensive list of all triggered and monitored alarm states.
          </p>
        </div>
        <div className="flex gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearchSubmit()}
              placeholder="Search alarms..."
              className="pl-10 pr-4 py-2 bg-white border border-slate-200 rounded-lg text-sm w-64 focus:ring-2 focus:ring-primary/20 outline-none"
            />
          </div>
          <LoadingButton
            isLoading={isExporting}
            onClick={handleExport}
            className="px-4 py-2 bg-white text-slate-700 text-sm font-semibold rounded-lg shadow-sm border border-slate-200 hover:bg-slate-50 flex items-center gap-2"
          >
            <Download size={16} /> Export Report
          </LoadingButton>
        </div>
      </div>

      {/* Summary cards */}
      <AlarmSummaryCards summary={summary} />

      {/* Filter tabs */}
      <div className="flex gap-2 p-1 bg-slate-100 rounded-xl w-max">
        {FILTER_TABS.map((f) => (
          <button
            key={f}
            onClick={() => handleFilterChange(f)}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
              currentFilter === f
                ? "bg-white text-primary shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Table */}
      <AlarmTable alarms={alarms} />

      {/* Pagination */}
      <Pagination
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={handlePageChange}
        onPageSizeChange={handlePageSizeChange}
      />
    </div>
  );
}
