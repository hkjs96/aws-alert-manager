"use client";

import type { Resource } from "@/types";
import { MonitoringToggle } from "@/components/shared/MonitoringToggle";
import { SeverityBadge } from "@/components/shared/SeverityBadge";

interface ResourceTableProps {
  resources: Resource[];
  selectedKeys: Set<string>;
  onSelectionChange: (keys: Set<string>) => void;
  onRowClick: (resource: Resource) => void;
  onToggleMonitoring: (id: string, enabled: boolean) => void;
  loading?: boolean;
}

export function ResourceTable({
  resources,
  selectedKeys,
  onSelectionChange,
  onRowClick,
  onToggleMonitoring,
  loading = false,
}: ResourceTableProps) {
  const allSelected = resources.length > 0 && resources.every((r) => selectedKeys.has(r.id));

  const toggleAll = () => {
    if (allSelected) onSelectionChange(new Set());
    else onSelectionChange(new Set(resources.map((r) => r.id)));
  };

  const toggleRow = (id: string) => {
    const next = new Set(selectedKeys);
    if (next.has(id)) next.delete(id); else next.add(id);
    onSelectionChange(next);
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-slate-200">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4 border-b border-slate-100 px-4 py-4">
            {Array.from({ length: 8 }).map((_, j) => (
              <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  if (resources.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 py-16 text-slate-400">
        <p>필터에 맞는 리소스가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-50 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
          <tr>
            <th className="w-10 px-4 py-3">
              <input type="checkbox" checked={allSelected} onChange={toggleAll} className="rounded" />
            </th>
            <th className="px-4 py-3">고객사</th>
            <th className="px-4 py-3">리소스 ID</th>
            <th className="px-4 py-3">이름</th>
            <th className="px-4 py-3">유형</th>
            <th className="px-4 py-3">어카운트</th>
            <th className="px-4 py-3">리전</th>
            <th className="px-4 py-3">모니터링</th>
            <th className="px-4 py-3">활성 알람</th>
          </tr>
        </thead>
        <tbody>
          {resources.map((r, i) => (
            <tr
              key={r.id}
              className={`border-b border-slate-100 cursor-pointer hover:bg-blue-50/50 ${i % 2 === 1 ? "bg-slate-50/50" : ""}`}
              onClick={() => onRowClick(r)}
            >
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={selectedKeys.has(r.id)} onChange={() => toggleRow(r.id)} className="rounded" />
              </td>
              <td className="px-4 py-3 text-slate-600">{r.customer_id}</td>
              <td className="px-4 py-3 font-mono text-xs text-blue-600">{r.id}</td>
              <td className="px-4 py-3 font-medium">{r.name}</td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {r.type}
                </span>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-500">{r.account_id}</td>
              <td className="px-4 py-3 text-slate-500">{r.region}</td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <MonitoringToggle enabled={r.monitoring} onChange={(v) => onToggleMonitoring(r.id, v)} />
              </td>
              <td className="px-4 py-3">
                {r.active_alarms.length > 0 ? (
                  <div className="flex gap-1">
                    {r.active_alarms.map((a) => (
                      <span key={a.severity} className="flex items-center gap-1">
                        <span className="text-xs font-medium">{a.count}</span>
                        <SeverityBadge severity={a.severity} />
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-slate-400">0 ACTIVE</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
