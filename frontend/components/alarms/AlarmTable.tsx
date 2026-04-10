"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ExternalLink, ChevronUp, ChevronDown } from "lucide-react";
import type { Alarm } from "@/types";

type SortDir = "asc" | "desc";

const COLUMNS: { key: string; label: string; sortable: boolean; align?: string }[] = [
  { key: "time", label: "Time", sortable: true },
  { key: "resource", label: "Resource", sortable: true },
  { key: "metric", label: "Metric", sortable: true },
  { key: "state", label: "State", sortable: true },
  { key: "value", label: "Value", sortable: false, align: "text-right" },
  { key: "actions", label: "Actions", sortable: false, align: "text-center" },
];

const STATE_ORDER: Record<string, number> = { ALARM: 0, INSUFFICIENT: 1, OK: 2, OFF: 3 };

const STATE_STYLES: Record<string, string> = {
  ALARM: "bg-error/10 text-error ring-error/20",
  INSUFFICIENT: "bg-amber-100 text-amber-700 ring-amber-500/20",
  OK: "bg-green-100 text-green-700 ring-green-500/20",
  OFF: "bg-slate-100 text-slate-500 ring-slate-400/20",
};

const DOT_STYLES: Record<string, string> = {
  ALARM: "bg-error animate-pulse",
  INSUFFICIENT: "bg-amber-500",
  OK: "bg-green-500",
  OFF: "bg-slate-400",
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

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest font-bold text-slate-500 border-b border-slate-100 bg-slate-50/50">
              {COLUMNS.map((col) => {
                const isActive = sortKey === col.key;
                return (
                  <th key={col.key}
                    className={`px-6 py-4 ${col.align ?? ""} ${col.sortable ? "cursor-pointer select-none hover:text-slate-800" : ""} ${isActive ? "text-slate-800" : ""}`}
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
          <tbody className="text-sm">
            {sorted.map((alarm, i) => (
              <tr key={alarm.id} className={`hover:bg-slate-50 transition-colors ${i % 2 === 1 ? "bg-slate-50/30" : ""}`}>
                <td className="px-6 py-4 font-mono text-xs text-slate-500">{alarm.time}</td>
                <td className="px-6 py-4">
                  <span className="font-bold text-slate-900 block">{alarm.resource}</span>
                  <span className="text-[10px] font-mono text-slate-400">{alarm.arn}</span>
                </td>
                <td className="px-6 py-4 font-medium text-slate-700">{alarm.metric}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-bold ring-1 ${STATE_STYLES[alarm.state] ?? STATE_STYLES.OFF}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${DOT_STYLES[alarm.state] ?? DOT_STYLES.OFF}`} />{alarm.state}
                  </span>
                </td>
                <td className={`px-6 py-4 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-error" : "text-slate-600"}`}>{alarm.value}</td>
                <td className="px-6 py-4 text-center">
                  <button onClick={() => router.push(`/resources/${encodeURIComponent(alarm.resource)}`)}
                    className="p-1.5 hover:bg-slate-200 rounded-md text-slate-500 transition-colors">
                    <ExternalLink size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
