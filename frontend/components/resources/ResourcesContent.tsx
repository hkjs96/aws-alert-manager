"use client";

import { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Download, RefreshCw } from "lucide-react";
import type { Resource } from "@/types";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { Pagination } from "@/components/shared/Pagination";
import { useMonitoringToggle } from "@/hooks/useMonitoringToggle";
import { downloadCsv } from "@/lib/exportCsv";
import { ResourceTable } from "./ResourceTable";
import { BulkActionBar } from "./BulkActionBar";
import { FilterBar } from "./FilterBar";
import { EnableModal } from "./EnableModal";
import { DisableModal } from "./DisableModal";

type SortDir = "asc" | "desc";

interface CustomerDto {
  id: string;
  name: string;
}

interface AccountDto {
  id: string;
  name: string;
  customerId: string;
}

interface ResourcesContentProps {
  resources: Resource[];
  customers: CustomerDto[];
  accounts: AccountDto[];
}

const DEFAULT_PAGE_SIZE = 25;
const ALARM_CRITICAL_WEIGHT = 10;
const ALARM_WARNING_WEIGHT = 1;

function alarmScore(alarms: { critical: number; warning: number }): number {
  return alarms.critical * ALARM_CRITICAL_WEIGHT + alarms.warning * ALARM_WARNING_WEIGHT;
}

export function ResourcesContent({
  resources,
  customers,
  accounts,
}: ResourcesContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const { loadingIds, toggle } = useMonitoringToggle();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<"enable" | "disable" | null>(null);
  const [search, setSearch] = useState("");
  const [customerFilter, setCustomerFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  // Customer 선택 시 해당 Customer의 Account만 표시
  const filteredAccounts = useMemo(
    () =>
      customerFilter
        ? accounts.filter((a) => a.customerId === customerFilter)
        : accounts,
    [accounts, customerFilter],
  );

  const handleCustomerChange = (v: string) => {
    setCustomerFilter(v);
    setAccountFilter("");
    setPage(1);
  };

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(1);
  };

  // 필터링
  const filtered = useMemo(() => {
    return resources.filter((r) => {
      if (customerFilter) {
        const accountIds = accounts
          .filter((a) => a.customerId === customerFilter)
          .map((a) => a.id);
        if (!accountIds.includes(r.account)) return false;
      }
      if (accountFilter && r.account !== accountFilter) return false;
      if (typeFilter && r.type !== typeFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        if (!r.name.toLowerCase().includes(q) && !r.id.toLowerCase().includes(q))
          return false;
      }
      return true;
    });
  }, [resources, customerFilter, accountFilter, typeFilter, search, accounts]);

  // 정렬
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "alarms") {
        cmp = alarmScore(a.alarms) - alarmScore(b.alarms);
      } else {
        const aVal = String(a[sortKey as keyof Resource] ?? "");
        const bVal = String(b[sortKey as keyof Resource] ?? "");
        cmp = aVal.localeCompare(bVal);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir]);

  // Client-side pagination
  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, page, pageSize]);

  // Selection analysis
  const selectedResources = resources.filter((r) => selected.has(r.id));
  const selectedTypes = useMemo(
    () => new Set(selectedResources.map((r) => r.type)),
    [selectedResources],
  );
  const isSameType = selectedTypes.size === 1;
  const selectedType = isSameType ? [...selectedTypes][0] : null;

  const handleToggleMonitoring = useCallback(
    async (id: string, currentState: boolean) => {
      const success = await toggle(id, currentState);
      if (success) router.refresh();
    },
    [toggle, router],
  );

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      const res = await fetch("/api/resources/sync", { method: "POST" });
      if (!res.ok) throw new Error("sync failed");
      const result = await res.json() as { discovered: number; updated: number; removed: number };
      showToast("success", `동기화 완료: ${result.discovered}개 발견, ${result.updated}개 업데이트, ${result.removed}개 제거`);
      router.refresh();
    } catch {
      showToast("error", "리소스 동기화에 실패했습니다.");
    } finally {
      setIsSyncing(false);
    }
  };

  const handleExport = async () => {
    setIsExporting(true);
    try {
      await downloadCsv("/api/resources/export", {}, "resources");
      showToast("success", "CSV 내보내기가 완료되었습니다.");
    } catch {
      showToast("error", "CSV 내보내기에 실패했습니다.");
    } finally {
      setIsExporting(false);
    }
  };

  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize);
    setPage(1);
  };

  const handleBulkComplete = () => {
    setModal(null);
    setSelected(new Set());
    router.refresh();
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
            Resources Inventory
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Manage and monitor AWS entities across all registered accounts.
          </p>
        </div>
        <div className="flex gap-3">
          <LoadingButton
            isLoading={isExporting}
            onClick={handleExport}
            className="bg-white border border-slate-200 px-4 py-2 rounded-xl text-sm font-semibold flex items-center gap-2 hover:bg-slate-50 shadow-sm"
          >
            <Download size={16} /> Export CSV
          </LoadingButton>
          <LoadingButton
            isLoading={isSyncing}
            onClick={handleSync}
            className="bg-primary text-white px-5 py-2 rounded-xl text-sm font-bold flex items-center gap-2 shadow-lg shadow-primary/20"
          >
            <RefreshCw size={16} /> Sync Resources
          </LoadingButton>
        </div>
      </div>

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

      {/* Bulk action bar */}
      <BulkActionBar
        selectedCount={selected.size}
        isMixedType={!isSameType && selected.size > 1}
        onEnable={() => setModal("enable")}
        onDisable={() => setModal("disable")}
      />

      {/* Resource table */}
      <ResourceTable
        resources={paginated}
        selectedKeys={selected}
        loadingToggleIds={loadingIds}
        onSelectionChange={setSelected}
        onToggleMonitoring={handleToggleMonitoring}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={handleSort}
      />

      {/* Pagination — client-side */}
      <Pagination
        page={page}
        pageSize={pageSize}
        total={sorted.length}
        onPageChange={setPage}
        onPageSizeChange={handlePageSizeChange}
      />

      {/* Modals */}
      {modal === "enable" && (
        <EnableModal
          selectedIds={[...selected]}
          selectedType={selectedType ?? null}
          isSameType={isSameType}
          onClose={() => setModal(null)}
          onComplete={handleBulkComplete}
        />
      )}
      {modal === "disable" && (
        <DisableModal
          selectedIds={[...selected]}
          onClose={() => setModal(null)}
          onComplete={handleBulkComplete}
        />
      )}
    </div>
  );
}
