"use client";

import { useRouter } from "next/navigation";
import { Database, ChevronUp, ChevronDown } from "lucide-react";
import type { Resource } from "@/types";

type SortDir = "asc" | "desc";

interface ResourceTableProps {
  resources: Resource[];
  selectedKeys: Set<string>;
  loadingToggleIds: Set<string>;
  onSelectionChange: (keys: Set<string>) => void;
  onToggleMonitoring: (id: string, current: boolean) => void;
  sortKey: string;
  sortDir: SortDir;
  onSort: (key: string) => void;
  totalResourceCount?: number;
  onClearFilters?: () => void;
}

const SORTABLE_COLUMNS: { key: string; label: string }[] = [
  { key: "name", label: "Resource" },
  { key: "region", label: "Region" },
  { key: "alarms", label: "Alarms" },
];

export function ResourceTable({
  resources,
  selectedKeys,
  loadingToggleIds,
  onSelectionChange,
  onToggleMonitoring,
  sortKey,
  sortDir,
  onSort,
  totalResourceCount = 0,
  onClearFilters,
}: ResourceTableProps) {
  const router = useRouter();
  const allSelected =
    resources.length > 0 && resources.every((r) => selectedKeys.has(r.id));

  const isEmpty = resources.length === 0;

  const toggleAll = () => {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(resources.map((r) => r.id)));
    }
  };

  const toggleOne = (id: string) => {
    const next = new Set(selectedKeys);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectionChange(next);
  };

  if (isEmpty) {
    return <EmptyState totalCount={totalResourceCount} onClearFilters={onClearFilters} />;
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <table className="w-full text-left border-collapse">
        <thead className="bg-slate-50">
          <tr className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <th className="px-6 py-4 w-12">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="rounded border-slate-300 text-primary focus:ring-primary"
              />
            </th>
            <th className="px-4 py-4">Status</th>
            {SORTABLE_COLUMNS.map((col) => {
              const isActive = sortKey === col.key;
              return (
                <th
                  key={col.key}
                  className={`px-4 py-4 cursor-pointer select-none hover:text-slate-800 ${isActive ? "text-slate-800" : ""}`}
                  onClick={() => onSort(col.key)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    <span className="inline-flex flex-col">
                      <ChevronUp
                        size={10}
                        className={isActive && sortDir === "asc" ? "text-slate-700" : "opacity-30"}
                      />
                      <ChevronDown
                        size={10}
                        className={isActive && sortDir === "desc" ? "text-slate-700" : "opacity-30"}
                      />
                    </span>
                  </span>
                </th>
              );
            })}
            <th className="px-4 py-4">Monitoring</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {resources.map((res, i) => (
            <tr
              key={res.id}
              onClick={() =>
                router.push(`/resources/${encodeURIComponent(res.name)}`)
              }
              className={`hover:bg-slate-50 cursor-pointer ${
                selectedKeys.has(res.id)
                  ? "bg-blue-50/40"
                  : i % 2 === 1
                    ? "bg-slate-50/20"
                    : ""
              }`}
            >
              <td className="px-6 py-3" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selectedKeys.has(res.id)}
                  onChange={() => toggleOne(res.id)}
                  className="rounded border-slate-300 text-primary focus:ring-primary"
                />
              </td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <StatusDot monitoring={res.monitoring} alarms={res.alarms} />
              </td>
              <td className="px-4 py-3">
                <div className="font-semibold text-slate-800 text-sm">{res.name}</div>
                <div className="text-xs text-slate-400">{res.type} · {res.account}</div>
              </td>
              <td className="px-4 py-3 text-sm font-medium text-slate-700">
                {res.region}
              </td>
              <td className="px-4 py-3">
                <AlarmBadges alarms={res.alarms} />
              </td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <MonitoringToggle
                  enabled={res.monitoring}
                  loading={loadingToggleIds.has(res.id)}
                  onToggle={() => onToggleMonitoring(res.id, res.monitoring)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState({
  totalCount,
  onClearFilters,
}: {
  totalCount: number;
  onClearFilters?: () => void;
}) {
  const hasResources = totalCount > 0;

  if (hasResources) {
    return (
      <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <span className="text-4xl mb-4">🔍</span>
          <h3 className="text-sm font-semibold text-slate-700 mb-1">검색 결과가 없습니다</h3>
          <p className="text-xs text-slate-400 mb-4">검색어나 필터 조건을 변경해보세요</p>
          {onClearFilters && (
            <button
              onClick={onClearFilters}
              className="px-4 py-1.5 bg-primary text-white text-xs font-semibold rounded-md hover:opacity-90 transition-opacity"
            >
              필터 초기화
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <span className="text-4xl mb-4">🌐</span>
        <h3 className="text-sm font-semibold text-slate-700 mb-1">모니터링 중인 리소스가 없습니다</h3>
        <p className="text-xs text-slate-400">리소스를 동기화해보세요</p>
      </div>
    </div>
  );
}

function MonitoringToggle({
  enabled,
  loading,
  onToggle,
}: {
  enabled: boolean;
  loading: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      disabled={loading}
      className={`w-8 h-4 rounded-full relative transition-colors ${
        loading ? "opacity-50 cursor-wait" : ""
      } ${enabled ? "bg-primary" : "bg-slate-300"}`}
    >
      <div
        className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${
          enabled ? "left-[18px]" : "left-0.5"
        }`}
      />
    </button>
  );
}

function StatusDot({
  monitoring,
  alarms,
}: {
  monitoring: boolean;
  alarms: { critical: number; warning: number };
}) {
  if (!monitoring) {
    return (
      <div className="relative inline-flex h-2.5 w-2.5">
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-slate-400" />
      </div>
    );
  }

  if (alarms.critical > 0) {
    return (
      <div className="relative inline-flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
      </div>
    );
  }

  if (alarms.warning > 0) {
    return (
      <div className="relative inline-flex h-2.5 w-2.5">
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
      </div>
    );
  }

  return (
    <div className="relative inline-flex h-2.5 w-2.5">
      <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
    </div>
  );
}

function AlarmBadges({
  alarms,
}: {
  alarms: { critical: number; warning: number };
}) {
  const hasCritical = alarms.critical > 0;
  const hasWarning = alarms.warning > 0;

  if (!hasCritical && !hasWarning) {
    return (
      <span className="text-green-600 text-[10px] font-bold">✓</span>
    );
  }

  return (
    <div className="flex items-center gap-1">
      {hasCritical && (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-700 border border-red-200">
          ● {alarms.critical}
        </span>
      )}
      {hasWarning && (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-200">
          ▲ {alarms.warning}
        </span>
      )}
    </div>
  );
}
