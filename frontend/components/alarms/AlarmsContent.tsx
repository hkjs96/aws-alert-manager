"use client";

import { useState, useMemo } from "react";
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
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

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

  const selCls = "bg-slate-50 border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">Active Alarms</h1>
          <p className="text-slate-500 text-sm mt-1">Comprehensive list of all triggered and monitored alarm states.</p>
        </div>
        <LoadingButton isLoading={isExporting} onClick={handleExport}
          className="px-4 py-2 bg-white text-slate-700 text-sm font-semibold rounded-lg shadow-sm border border-slate-200 hover:bg-slate-50 flex items-center gap-2">
          <Download size={16} /> Export Report
        </LoadingButton>
      </div>

      {/* Summary cards */}
      <AlarmSummaryCards summary={summary} />

      {/* Filter bar */}
      <section className="bg-white/80 backdrop-blur rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-4 items-center border border-slate-200 shadow-sm">
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Customer</label>
          <select value={customerFilter} onChange={(e) => handleCustomerChange(e.target.value)} className={`w-full ${selCls}`}>
            <option value="">All Customers</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Account</label>
          <select value={accountFilter} onChange={(e) => { setAccountFilter(e.target.value); setPage(1); }} className={`w-full ${selCls}`}>
            <option value="">All Accounts</option>
            {filteredAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Resource Type</label>
          <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }} className={`w-full ${selCls}`}>
            <option value="">All Types</option>
            {SUPPORTED_RESOURCE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Quick Search</label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
            <input type="text" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Resource or Metric..."
              className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none" />
          </div>
        </div>
      </section>

      {/* State filter tabs */}
      <div className="flex gap-2 p-1 bg-slate-100 rounded-xl w-max">
        {FILTER_TABS.map((f) => (
          <button key={f} onClick={() => { setStateFilter(f); setPage(1); }}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
              stateFilter === f ? "bg-white text-primary shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}>
            {f}
          </button>
        ))}
      </div>

      {/* Table */}
      <AlarmTable alarms={paginated} />

      {/* Pagination */}
      <Pagination page={page} pageSize={pageSize} total={filtered.length}
        onPageChange={setPage} onPageSizeChange={(s) => { setPageSize(s); setPage(1); }} />
    </div>
  );
}
