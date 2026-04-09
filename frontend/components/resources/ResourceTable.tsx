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
}

const SORTABLE_COLUMNS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "type", label: "Type" },
  { key: "account", label: "Account" },
  { key: "region", label: "Region" },
  { key: "alarms", label: "Active Alarms" },
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
}: ResourceTableProps) {
  const router = useRouter();
  const allSelected =
    resources.length > 0 && resources.every((r) => selectedKeys.has(r.id));

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
            <th className="px-4 py-4">Resource ID</th>
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
              <td className="px-4 py-3 font-mono text-xs text-primary font-medium">
                {res.id}
              </td>
              <td className="px-4 py-3 font-semibold text-sm text-slate-900">
                {res.name}
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2 bg-slate-100 rounded-full px-2 py-1 w-max">
                  <Database size={12} className="text-slate-500" />
                  <span className="text-[10px] font-bold uppercase">
                    {res.type}
                  </span>
                </div>
              </td>
              <td className="px-4 py-3 text-sm text-slate-500">{res.account}</td>
              <td className="px-4 py-3 text-sm font-medium text-slate-700">
                {res.region}
              </td>
              <td className="px-4 py-3">
                <AlarmBadge alarms={res.alarms} />
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

function AlarmBadge({
  alarms,
}: {
  alarms: { critical: number; warning: number };
}) {
  if (alarms.critical > 0) {
    return (
      <span className="bg-error/10 text-error px-2 py-0.5 rounded text-[10px] font-black border border-error/20 flex items-center gap-1 w-max">
        <span className="w-1 h-1 bg-error rounded-full animate-pulse" />
        {alarms.critical} CRITICAL
      </span>
    );
  }
  if (alarms.warning > 0) {
    return (
      <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-[10px] font-black border border-amber-200">
        {alarms.warning} WARNING
      </span>
    );
  }
  return (
    <span className="text-slate-400 text-[10px] font-bold uppercase bg-slate-100 px-2 py-0.5 rounded">
      0 ACTIVE
    </span>
  );
}
