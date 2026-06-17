"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Download, RefreshCw } from "lucide-react";
import type { Resource } from "@/types";
import { useToast } from "@/components/shared/Toast";
import { Button } from "@/components/shared/Button";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { Pagination } from "@/components/shared/Pagination";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { useMonitoringToggle } from "@/hooks/useMonitoringToggle";
import { useOwnedCustomers } from "@/hooks/useOwnedCustomers";
import { OwnedEmptyState } from "@/components/shared/OwnedEmptyState";
import { SyncScopeModal } from "@/components/shared/SyncScopeModal";
import { SyncProgressModal } from "@/components/shared/SyncProgressModal";
import { syncResources } from "@/lib/api-functions";
import { downloadCsv } from "@/lib/exportCsv";
import { ResourceTable } from "./ResourceTable";
import { BulkActionBar } from "./BulkActionBar";
import { FilterBar } from "./FilterBar";
import { EnableModal } from "./EnableModal";
import { DisableModal } from "./DisableModal";

type SortDir = "asc" | "desc";
type PendingToggle = {
  id: string;
  name: string;
  currentState: boolean;
};

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
  initialSearch?: string;
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
  initialSearch = "",
}: ResourcesContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const [localResources, setLocalResources] = useState<Resource[]>(resources);

  useEffect(() => {
    setLocalResources(resources);
  }, [resources]);

  // 상단바 전역 검색(/resources?search=)에서 넘어온 쿼리를 반영 (네비게이션마다)
  useEffect(() => {
    setSearch(initialSearch);
    setPage(1);
  }, [initialSearch]);

  const { loadingIds, toggle } = useMonitoringToggle();
  const { ownedCustomerIds, isLoading: isOwnedLoading } = useOwnedCustomers();

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
  const [isExporting, setIsExporting] = useState(false);
  const [isSyncScopeOpen, setIsSyncScopeOpen] = useState(false);
  const [isSyncProgressOpen, setIsSyncProgressOpen] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");
  const [pendingToggle, setPendingToggle] = useState<PendingToggle | null>(null);

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

  // 담당 고객사에 속한 account_id 목록 (owned scope)
  const ownedAccountIds = useMemo(
    () =>
      accounts
        .filter((a) => ownedCustomerIds.includes(a.customerId))
        .map((a) => a.id),
    [accounts, ownedCustomerIds],
  );

  // 필터링
  const filtered = useMemo(() => {
    return localResources.filter((r) => {
      // 담당 고객사 범위 필터 (explicit customerFilter가 없을 때)
      if (!customerFilter && ownedCustomerIds.length > 0) {
        if (!ownedAccountIds.includes(r.account)) return false;
      }
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
  }, [localResources, customerFilter, accountFilter, typeFilter, search, accounts, ownedAccountIds, ownedCustomerIds]);

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
  const selectedResources = localResources.filter((r) => selected.has(r.id));
  const selectedTypes = useMemo(
    () => new Set(selectedResources.map((r) => r.type)),
    [selectedResources],
  );
  const isSameType = selectedTypes.size === 1;
  const selectedType = isSameType ? [...selectedTypes][0] : null;

  const handleToggleMonitoring = useCallback(
    (id: string, currentState: boolean) => {
      const resource = localResources.find((item) => item.id === id);
      setPendingToggle({
        id,
        name: resource?.name || id,
        currentState,
      });
    },
    [localResources],
  );

  const confirmToggleMonitoring = useCallback(
    async () => {
      if (!pendingToggle) return;
      const { id, currentState } = pendingToggle;
      setPendingToggle(null);

      const targetState = !currentState;
      // Optimistic update
      setLocalResources((prev) =>
        prev.map((r) => (r.id === id ? { ...r, monitoring: targetState } : r))
      );

      const success = await toggle(id, currentState);
      if (!success) {
        // Rollback
        setLocalResources((prev) =>
          prev.map((r) => (r.id === id ? { ...r, monitoring: currentState } : r))
        );
      }
    },
    [pendingToggle, toggle],
  );

  const handleStartSync = async (scope: { customer_id?: string; account_id?: string; regions?: string[] }) => {
    setIsSyncScopeOpen(false);
    try {
      const res = await syncResources(scope);
      setActiveJobId(res.job_id);
      setIsSyncProgressOpen(true);
    } catch {
      showToast("error", "Failed to start resource sync job.");
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

  const handleClearFilters = () => {
    setSearch("");
    setCustomerFilter("");
    setAccountFilter("");
    setTypeFilter("");
    setPage(1);
  };

  const handleBulkEnableComplete = () => {
    setLocalResources((prev) =>
      prev.map((r) => (selected.has(r.id) ? { ...r, monitoring: true } : r))
    );
    setModal(null);
    setSelected(new Set());
  };

  const handleBulkDisableComplete = () => {
    setLocalResources((prev) =>
      prev.map((r) => (selected.has(r.id) ? { ...r, monitoring: false } : r))
    );
    setModal(null);
    setSelected(new Set());
  };

  if (!isOwnedLoading && ownedCustomerIds.length === 0) {
    return <OwnedEmptyState />;
  }

  if (isOwnedLoading) {
    return <div className="py-20 text-center text-sm text-slate-400">로딩 중...</div>;
  }

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
          <Button
            onClick={() => setIsSyncScopeOpen(true)}
            className="bg-primary text-white px-5 py-2 rounded-xl text-sm font-bold flex items-center gap-2 shadow-lg shadow-primary/20"
          >
            <RefreshCw size={16} /> Sync Resources
          </Button>
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
        onClearAll={handleClearFilters}
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
        totalResourceCount={localResources.length}
        onClearFilters={handleClearFilters}
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
          onComplete={handleBulkEnableComplete}
        />
      )}
      {modal === "disable" && (
        <DisableModal
          selectedIds={[...selected]}
          onClose={() => setModal(null)}
          onComplete={handleBulkDisableComplete}
        />
      )}
      <ConfirmDialog
        isOpen={pendingToggle !== null}
        title={pendingToggle?.currentState ? "Turn monitoring off?" : "Turn monitoring on?"}
        message={
          pendingToggle
            ? `${pendingToggle.name} (${pendingToggle.id}) monitoring will be ${pendingToggle.currentState ? "disabled" : "enabled"}. Continue?`
            : ""
        }
        confirmLabel={pendingToggle?.currentState ? "Turn Off" : "Turn On"}
        cancelLabel="Cancel"
        variant={pendingToggle?.currentState ? "danger" : "default"}
        onConfirm={confirmToggleMonitoring}
        onCancel={() => setPendingToggle(null)}
      />

      {/* Resource inventory sync (알람 싱크와 동일한 비동기 흐름) */}
      <SyncScopeModal
        isOpen={isSyncScopeOpen}
        onClose={() => setIsSyncScopeOpen(false)}
        customers={customers}
        accounts={accounts}
        onStartSync={handleStartSync}
        target="resources"
      />
      <SyncProgressModal
        isOpen={isSyncProgressOpen}
        jobId={activeJobId}
        target="resources"
        onClose={() => setIsSyncProgressOpen(false)}
        onSuccess={() => {
          showToast("success", "Resource inventory updated successfully.");
          router.refresh();
        }}
      />
    </div>
  );
}
