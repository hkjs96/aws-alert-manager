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

interface ResourcesContentProps {
  resources: Resource[];
  total: number;
  page: number;
  pageSize: number;
}

export function ResourcesContent({
  resources,
  total,
  page,
  pageSize,
}: ResourcesContentProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const { loadingIds, toggle } = useMonitoringToggle();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<"enable" | "disable" | null>(null);
  const [search, setSearch] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  // Local search filter (client-side for quick search within current page)
  const filtered = useMemo(
    () =>
      resources.filter(
        (r) =>
          r.name.toLowerCase().includes(search.toLowerCase()) ||
          r.id.toLowerCase().includes(search.toLowerCase()),
      ),
    [resources, search],
  );

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
      // Simulate API call — replace with syncResources() when backend ready
      await new Promise((resolve) => setTimeout(resolve, 1000));
      showToast("success", "동기화 완료: 3개 발견, 1개 업데이트, 0개 제거");
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

  const handlePageChange = (newPage: number) => {
    const params = new URLSearchParams();
    params.set("page", String(newPage));
    params.set("page_size", String(pageSize));
    router.push(`/resources?${params.toString()}`);
  };

  const handlePageSizeChange = (newSize: number) => {
    const params = new URLSearchParams();
    params.set("page", "1");
    params.set("page_size", String(newSize));
    router.push(`/resources?${params.toString()}`);
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
      <FilterBar search={search} onSearchChange={setSearch} />

      {/* Bulk action bar */}
      <BulkActionBar
        selectedCount={selected.size}
        isMixedType={!isSameType && selected.size > 1}
        onEnable={() => setModal("enable")}
        onDisable={() => setModal("disable")}
      />

      {/* Resource table */}
      <ResourceTable
        resources={filtered}
        selectedKeys={selected}
        loadingToggleIds={loadingIds}
        onSelectionChange={setSelected}
        onToggleMonitoring={handleToggleMonitoring}
      />

      {/* Pagination */}
      <Pagination
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={handlePageChange}
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

