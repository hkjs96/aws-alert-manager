"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Download } from "lucide-react";
import type { Alarm } from "@/types";
import type { AlarmSummary, AlarmStateFilter } from "@/types/api";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { Pagination } from "@/components/shared/Pagination";
import { FilterBar } from "@/components/resources/FilterBar";
import { downloadCsv } from "@/lib/exportCsv";
import { AlarmSummaryCards } from "./AlarmSummaryCards";
import { AlarmTable } from "./AlarmTable";

const FILTER_TABS: AlarmStateFilter[] = ["ALL", "ALARM", "INSUFFICIENT", "OK", "OFF"];

const DEFAULT_PAGE_SIZE = 25;

interface CustomerDto { id: string; name: string }
interface AccountDto { id: string; name: string; customerId: string }

interface AlarmsContentProps {
  alarms: Alarm[];
  summary: AlarmSummary;
  customers: CustomerDto[];
  accounts: AccountDto[];
}

export function AlarmsContent({ alarms, summary, customers, accounts }: AlarmsContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<AlarmStateFilter>("ALL");
  const [customerFilter, setCustomerFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [isExporting, setIsExporting] = useState(false);

  const filteredAccounts = useMemo(
    () => customerFilter ? accounts.filter((a) => a.customerId === customerFilter) : accounts,
    [accounts, customerFilter],
  );

  const handleCustomerChange = (v: string) => {
    setCustomerFilter(v);
    setAccountFilter("");
    setPage(1);
  };

  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: 0, ALARM: 0, INSUFFICIENT: 0, OK: 0, OFF: 0 };
    alarms.forEach((a) => {
      counts.ALL++;
      if (a.state in counts) counts[a.state]++;
    });
    return counts;
  }, [alarms]);

  const filtered = useMemo(() => {
    return alarms.filter((a) => {
      if (stateFilter !== "ALL" && a.state !== stateFilter) return false;
      if (typeFilter && a.type !== typeFilter) return false;
      if (accountFilter && !a.arn.includes(accountFilter)) return false;
      if (customerFilter) {
        const ids = accounts.filter((acc) => acc.customerId === customerFilter).map((acc) => acc.id);
        if (!ids.some((id) => a.arn.includes(id))) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        if (!a.resource.toLowerCase().includes(q) && !a.metric.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [alarms, stateFilter, customerFilter, accountFilter, typeFilter, search, accounts]);

  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, page, pageSize]);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const filters: Record<string, string | undefined> = {};
      if (stateFilter !== "ALL") filters.state = stateFilter;
      if (search) filters.search = search;
      await downloadCsv("/api/alarms/export", filters, "alarms");
      showToast("success", "CSV export completed.");
    } catch {
      showToast("error", "CSV export failed.");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">Active Alarms</h1>
          <p className="text-sm text-slate-500 mt-1">Comprehensive list of all triggered and monitored alarm states.</p>
        </div>
        <div className="flex items-center gap-3">
          <LoadingButton isLoading={isExporting} onClick={handleExport}
            className="px-4 py-2 bg-white text-slate-700 text-sm font-semibold rounded-lg shadow-sm border border-slate-200 hover:bg-slate-50 flex items-center gap-2">
            <Download size={16} /> Export Report
          </LoadingButton>
        </div>
        {/* Note: Export button kept as LoadingButton for now to preserve custom styling */}
      </header>

      {/* Summary cards */}
      <AlarmSummaryCards summary={summary} />

      {/* Filter bar */}
      <FilterBar
        search={search}
        onSearchChange={(v) => { setSearch(v); setPage(1); }}
        customerFilter={customerFilter}
        onCustomerChange={handleCustomerChange}
        accountFilter={accountFilter}
        onAccountChange={(v) => { setAccountFilter(v); setPage(1); }}
        typeFilter={typeFilter}
        onTypeChange={(v) => { setTypeFilter(v); setPage(1); }}
        customers={customers}
        accounts={filteredAccounts}
      />

      {/* State filter tabs */}
      <div className="flex gap-2 p-1 bg-slate-100 rounded-xl w-max">
        {FILTER_TABS.map((f) => {
          const count = stateCounts[f];
          const badgeColor = f === "ALL" ? "bg-slate-400 text-white" : f === "ALARM" ? "bg-red-500 text-white" : f === "INSUFFICIENT" ? "bg-amber-500 text-white" : f === "OK" ? "bg-green-500 text-white" : "bg-slate-400 text-white";
          return (
            <button key={f} onClick={() => { setStateFilter(f); setPage(1); }}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all inline-flex items-center gap-1 ${
                stateFilter === f ? "bg-white text-primary shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}>
              {f}
              {count > 0 && (
                <span className={`inline-flex items-center justify-center w-[18px] h-[18px] rounded-full text-[9px] font-bold ml-1 ${badgeColor}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Table */}
      <AlarmTable alarms={paginated} />

      {/* Pagination */}
      <Pagination page={page} pageSize={pageSize} total={filtered.length}
        onPageChange={setPage} onPageSizeChange={(s) => { setPageSize(s); setPage(1); }} />
    </div>
  );
}
