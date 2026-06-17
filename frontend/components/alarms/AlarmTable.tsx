"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ChevronUp, ChevronDown } from "lucide-react";
import type { Alarm } from "@/types";
import { ResourceTypeIcon } from "@/components/shared/ResourceTypeIcon";
import { formatRelativeTime } from "@/lib/time-utils";
import { encodeResourceId } from "@/lib/resource-id";

type SortDir = "asc" | "desc";

const COLUMNS: { key: string; label: string; sortable: boolean; align?: string }[] = [
  { key: "time", label: "Time", sortable: true },
  { key: "resource", label: "Resource", sortable: true },
  { key: "metric", label: "Metric", sortable: true },
  { key: "state", label: "State", sortable: true },
  { key: "value", label: "Value", sortable: false, align: "text-right" },
];

const STATE_ORDER: Record<string, number> = { ALARM: 0, INSUFFICIENT_DATA: 1, OK: 2, OFF: 3 };

const STATE_STYLES: Record<string, string> = {
  ALARM: "bg-error/10 text-error ring-error/20",
  INSUFFICIENT_DATA: "bg-amber-100 text-amber-700 ring-amber-500/20",
  OK: "bg-green-100 text-green-700 ring-green-500/20",
  OFF: "bg-slate-100 text-slate-500 ring-slate-400/20",
};

const DOT_STYLES: Record<string, string> = {
  ALARM: "bg-error animate-pulse",
  INSUFFICIENT_DATA: "bg-amber-500",
  OK: "bg-green-500",
  OFF: "bg-slate-400",
};

const STATE_LABEL: Record<string, string> = {
  INSUFFICIENT_DATA: "INSUFFICIENT",
};

interface AlarmTableProps {
  alarms: Alarm[];
}

export function AlarmTable({ alarms }: AlarmTableProps) {
  const router = useRouter();
  const [sortKey, setSortKey] = useState("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sorted = useMemo(() => {
    return [...alarms].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "state") {
        cmp = (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9);
      } else {
        const aVal = String(a[sortKey as keyof Alarm] ?? "");
        const bVal = String(b[sortKey as keyof Alarm] ?? "");
        cmp = aVal.localeCompare(bVal);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [alarms, sortKey, sortDir]);

  if (alarms.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-sm font-semibold text-slate-600">No alarms match the current filter</p>
          <p className="text-xs text-slate-400 mt-1">Try adjusting your filter criteria</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              {COLUMNS.map((col) => {
                const isActive = sortKey === col.key;
                return (
                  <th key={col.key}
                    className={`px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider ${col.align ?? ""} ${col.sortable ? "cursor-pointer select-none hover:text-slate-800" : ""} ${isActive ? "text-slate-800" : ""}`}
                    onClick={col.sortable ? () => handleSort(col.key) : undefined}>
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {col.sortable && (
                        <span className="inline-flex flex-col">
                          <ChevronUp size={9} className={isActive && sortDir === "asc" ? "text-slate-700" : "opacity-30"} />
                          <ChevronDown size={9} className={isActive && sortDir === "desc" ? "text-slate-700" : "opacity-30"} />
                        </span>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sorted.map((alarm) => (
              <tr
                key={alarm.id}
                onClick={() => router.push(`/resources/${encodeResourceId(alarm.resource)}`)}
                className={`cursor-pointer transition-colors ${alarm.state === "ALARM" ? "bg-red-50 border-l-2 border-l-red-500 hover:bg-red-100/60" : "hover:bg-slate-50"}`}
              >
                <td className="px-4 py-3 font-mono text-xs text-slate-500">
                  <span title={alarm.time}>{formatRelativeTime(alarm.time)}</span>
                </td>
                <td className="px-4 py-3" title={alarm.arn}>
                  <span className="font-bold text-slate-900">{alarm.resource}</span>
                  <ResourceTypeIcon type={alarm.type} className="ml-2 align-middle" />
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-700">{alarm.metric}</div>
                  {alarm.mount_path && (
                    <div className="mt-1 inline-flex rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-500">
                      {alarm.mount_path}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-bold ring-1 ${STATE_STYLES[alarm.state] ?? STATE_STYLES.OFF}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${DOT_STYLES[alarm.state] ?? DOT_STYLES.OFF}`} />{STATE_LABEL[alarm.state] ?? alarm.state}
                  </span>
                </td>
                <td className={`px-4 py-3 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-red-600" : "text-slate-600"}`}>{alarm.value ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
