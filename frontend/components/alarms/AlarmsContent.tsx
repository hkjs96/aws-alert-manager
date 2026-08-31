"use client";

import { useState, useMemo, useDeferredValue } from "react";
import { useRouter } from "next/navigation";
import { Download, RefreshCw } from "lucide-react";
import type { Alarm } from "@/types";
import type { AlarmSummary, AlarmStateFilter } from "@/types/api";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { Pagination } from "@/components/shared/Pagination";
import { FilterBar } from "@/components/resources/FilterBar";
import { downloadCsv } from "@/lib/exportCsv";
import { AlarmSummaryCards } from "./AlarmSummaryCards";
import { AlarmTable, sortAlarms, type AlarmSortDir } from "./AlarmTable";
import { useOwnedCustomers } from "@/hooks/useOwnedCustomers";
import { OwnedEmptyState } from "@/components/shared/OwnedEmptyState";
import { syncAlarms } from "@/lib/api-functions";
import { SyncScopeModal } from "@/components/shared/SyncScopeModal";
import { SyncProgressModal } from "@/components/shared/SyncProgressModal";

const FILTER_TABS: AlarmStateFilter[] = ["ALL", "ALARM", "INSUFFICIENT_DATA", "OK", "OFF"];

const TAB_LABEL: Record<AlarmStateFilter, string> = {
  ALL: "ALL",
  ALARM: "ALARM",
  INSUFFICIENT_DATA: "INSUFFICIENT",
  OK: "OK",
  OFF: "OFF",
};

const DEFAULT_PAGE_SIZE = 25;

interface CustomerDto { id: string; name: string }
interface AccountDto { id: string; name: string; customerId: string; regions?: string[] }

interface AlarmsContentProps {
  alarms: Alarm[];
  summary: AlarmSummary;
  customers: CustomerDto[];
  accounts: AccountDto[];
}

export function AlarmsContent({ alarms, summary, customers, accounts }: AlarmsContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const { ownedCustomerIds, isLoading: isOwnedLoading } = useOwnedCustomers();
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<AlarmStateFilter>("ALL");
  const [customerFilter, setCustomerFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  // 정렬은 페이지 슬라이스 전에 전체 필터 결과에 적용한다 (테이블 내부 정렬은 현재 페이지만 정렬하던 결함)
  const [sortKey, setSortKey] = useState("time");
  const [sortDir, setSortDir] = useState<AlarmSortDir>("desc");
  const [isExporting, setIsExporting] = useState(false);

  const [isSyncScopeOpen, setIsSyncScopeOpen] = useState(false);
  const [isSyncProgressOpen, setIsSyncProgressOpen] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");

  const handleStartSync = async (scope: { customer_id?: string; account_id?: string; regions?: string[] }) => {
    setIsSyncScopeOpen(false);
    try {
      const res = await syncAlarms(scope);
      setActiveJobId(res.job_id);
      setIsSyncProgressOpen(true);
    } catch {
      showToast("error", "Failed to start alarm sync job.");
    }
  };

  const filteredAccounts = useMemo(
    () => customerFilter ? accounts.filter((a) => a.customerId === customerFilter) : accounts,
    [accounts, customerFilter],
  );

  const handleCustomerChange = (v: string) => {
    setCustomerFilter(v);
    setAccountFilter("");
    setPage(1);
  };

  const ownedAccountIds = useMemo(
    () => accounts.filter((a) => ownedCustomerIds.includes(a.customerId)).map((a) => a.id),
    [accounts, ownedCustomerIds],
  );

  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: 0, ALARM: 0, INSUFFICIENT_DATA: 0, OK: 0, OFF: 0 };
    alarms.forEach((a) => {
      counts.ALL = (counts.ALL ?? 0) + 1;
      if (a.state in counts) counts[a.state] = (counts[a.state] ?? 0) + 1;
    });
    return counts;
  }, [alarms]);

  // 조회 인덱스: 알람마다 accounts 배열을 다시 훑지 않도록 한 번만 만든다 (O(n×m) → O(n)).
  const ownedAccountIdSet = useMemo(() => new Set(ownedAccountIds), [ownedAccountIds]);
  const customerAccountIds = useMemo(() => {
    const map = new Map<string, Set<string>>();
    accounts.forEach((acc) => {
      if (!map.has(acc.customerId)) map.set(acc.customerId, new Set());
      map.get(acc.customerId)!.add(acc.id);
    });
    return map;
  }, [accounts]);

  // 검색어는 지연 값으로 필터링 — 입력은 즉시 반영되고 목록 재계산은 뒤따른다.
  const deferredSearch = useDeferredValue(search);

  const filtered = useMemo(() => {
    const q = deferredSearch.toLowerCase();
    const customerAccounts = customerFilter ? customerAccountIds.get(customerFilter) : null;
    return alarms.filter((a) => {
      const account = a.account ?? "";
      // 담당 고객사 범위 필터 (explicit customerFilter가 없을 때)
      if (!customerFilter && ownedAccountIds.length > 0) {
        if (!ownedAccountIdSet.has(account)) return false;
      }
      if (stateFilter !== "ALL" && a.state !== stateFilter) return false;
      if (typeFilter && a.type !== typeFilter) return false;
      if (accountFilter && account !== accountFilter) return false;
      if (customerFilter && !customerAccounts?.has(account)) return false;
      if (q) {
        const resource = a.resource ?? "";
        const metric = a.metric ?? "";
        if (!resource.toLowerCase().includes(q) && !metric.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [alarms, stateFilter, customerFilter, accountFilter, typeFilter, deferredSearch, customerAccountIds, ownedAccountIdSet, ownedAccountIds]);

  const sorted = useMemo(() => sortAlarms(filtered, sortKey, sortDir), [filtered, sortKey, sortDir]);

  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, page, pageSize]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(1); // 정렬이 바뀌면 첫 페이지부터 (ResourcesContent와 동일 관례)
  };

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

  if (!isOwnedLoading && ownedCustomerIds.length === 0) {
    return <OwnedEmptyState />;
  }

  if (isOwnedLoading) {
    return <div className="py-20 text-center text-sm text-slate-400">로딩 중...</div>;
  }

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">Active Alarms</h1>
          <p className="text-sm text-slate-500 mt-1">Comprehensive list of all triggered and monitored alarm states.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            onClick={() => setIsSyncScopeOpen(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg shadow-sm flex items-center gap-2"
          >
            <RefreshCw size={16} /> Sync Alarms
          </Button>
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
        onClearAll={() => {
          setSearch("");
          setCustomerFilter("");
          setAccountFilter("");
          setTypeFilter("");
          setPage(1);
        }}
      />

      {/* State filter tabs */}
      <div className="flex gap-2 p-1 bg-slate-100 rounded-xl w-max">
        {FILTER_TABS.map((f) => {
          const count = stateCounts[f] ?? 0;
          const badgeColor = f === "ALL" ? "bg-slate-400 text-white" : f === "ALARM" ? "bg-red-500 text-white" : f === "INSUFFICIENT_DATA" ? "bg-amber-500 text-white" : f === "OK" ? "bg-green-500 text-white" : "bg-slate-400 text-white";
          return (
            <button key={f} onClick={() => { setStateFilter(f); setPage(1); }}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all inline-flex items-center gap-1 ${
                stateFilter === f ? "bg-white text-primary shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}>
              {TAB_LABEL[f]}
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
      <AlarmTable alarms={paginated} sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />

      {/* Pagination */}
      <Pagination page={page} pageSize={pageSize} total={filtered.length}
        onPageChange={setPage} onPageSizeChange={(s) => { setPageSize(s); setPage(1); }} />

      {/* Modals */}
      <SyncScopeModal
        isOpen={isSyncScopeOpen}
        onClose={() => setIsSyncScopeOpen(false)}
        customers={customers}
        accounts={accounts}
        onStartSync={handleStartSync}
      />
      <SyncProgressModal
        isOpen={isSyncProgressOpen}
        jobId={activeJobId}
        onClose={() => setIsSyncProgressOpen(false)}
        onSuccess={() => {
          showToast("success", "Alarm database updated successfully.");
          router.refresh();
        }}
      />
    </div>
  );
}
