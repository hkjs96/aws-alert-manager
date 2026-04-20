"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Search, ChevronUp, ChevronDown } from "lucide-react";
import { Pagination } from "@/components/shared/Pagination";
import type { Alarm } from "@/types";

const DEFAULT_PAGE_SIZE = 10;
type SortDir = "asc" | "desc";

const COLUMNS: { key: string; label: string; sortable: boolean; align?: string }[] = [
  { key: "time", label: "Time", sortable: true },
  { key: "resource", label: "Resource", sortable: true },
  { key: "type", label: "Type", sortable: true },
  { key: "metric", label: "Metric", sortable: true },
  { key: "state", label: "State", sortable: true },
  { key: "value", label: "Value/Threshold", sortable: false, align: "text-right" },
];

const STATE_ORDER: Record<string, number> = { ALARM: 0, INSUFFICIENT: 1, OK: 2, OFF: 3 };

function stateRing(s: string) {
  const m: Record<string, string> = {
    ALARM: "bg-error/10 text-error ring-error/20",
    INSUFFICIENT: "bg-amber-100 text-amber-700 ring-amber-500/20",
    OK: "bg-green-100 text-green-700 ring-green-500/20",
    OFF: "bg-slate-100 text-slate-500 ring-slate-400/20",
  };
  return m[s] ?? m.OFF;
}

function stateDot(s: string) {
  const m: Record<string, string> = {
    ALARM: "bg-error animate-pulse",
    INSUFFICIENT: "bg-amber-500",
    OK: "bg-green-500",
    OFF: "bg-slate-400",
  };
  return m[s] ?? m.OFF;
}

interface RecentAlarmsTableProps {
  alarms: Alarm[];
}

export function RecentAlarmsTable({ alarms }: RecentAlarmsTableProps) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [sortKey, setSortKey] = useState("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(1);
  };

  const filtered = useMemo(
    () => alarms.filter((a) =>
      a.resource.toLowerCase().includes(search.toLowerCase()) ||
      a.metric.toLowerCase().includes(search.toLowerCase()),
    ),
    [alarms, search],
  );

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
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
  }, [filtered, sortKey, sortDir]);

  const paged = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, page, pageSize]);

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="px-8 py-6 flex justify-between items-center bg-slate-50/50">
        <h3 className="font-headline font-bold text-lg text-slate-900">Recent Alarm Triggers</h3>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input type="text" value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search resources or metrics..."
            className="pl-10 pr-4 py-1.5 bg-white border border-slate-200 rounded-lg text-sm w-64 focus:ring-2 focus:ring-primary/20 outline-none" />
        </div>
      </div>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest font-bold text-slate-500 border-b border-slate-100">
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
          {paged.map((alarm, i) => (
            <tr key={alarm.id} onClick={() => router.push(`/resources/${encodeURIComponent(alarm.resource)}`)}
              className={`hover:bg-slate-50 cursor-pointer ${i % 2 === 1 ? "bg-slate-50/30" : ""}`}>
              <td className="px-6 py-4 font-mono text-xs text-slate-500">{alarm.time}</td>
              <td className="px-6 py-4">
                <span className="font-bold text-slate-900 block">{alarm.resource}</span>
                <span className="text-[10px] font-mono text-slate-400">{alarm.arn}</span>
              </td>
              <td className="px-6 py-4"><span className="bg-slate-100 px-2 py-0.5 rounded text-[10px] font-bold text-slate-600">{alarm.type}</span></td>
              <td className="px-6 py-4 font-medium text-slate-700">{alarm.metric}</td>
              <td className="px-6 py-4">
                <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-bold ring-1 ${stateRing(alarm.state)}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${stateDot(alarm.state)}`} />{alarm.state}
                </span>
              </td>
              <td className={`px-6 py-4 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-error" : "text-slate-600"}`}>{alarm.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-8 py-4 bg-slate-50/30 border-t border-slate-100">
        <Pagination page={page} pageSize={pageSize} total={sorted.length}
          onPageChange={setPage} onPageSizeChange={(s) => { setPageSize(s); setPage(1); }} />
      </div>
    </div>
  );
}
