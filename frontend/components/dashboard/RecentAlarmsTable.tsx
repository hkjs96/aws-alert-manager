"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Search, SlidersHorizontal } from "lucide-react";
import { Pagination } from "@/components/shared/Pagination";
import type { Alarm } from "@/types";

const DEFAULT_PAGE_SIZE = 10;

interface RecentAlarmsTableProps {
  alarms: Alarm[];
}

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

export function RecentAlarmsTable({ alarms }: RecentAlarmsTableProps) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const filtered = useMemo(
    () =>
      alarms.filter(
        (a) =>
          a.resource.toLowerCase().includes(search.toLowerCase()) ||
          a.metric.toLowerCase().includes(search.toLowerCase()),
      ),
    [alarms, search],
  );

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const paged = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, page, pageSize]);

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="px-8 py-6 flex justify-between items-center bg-slate-50/50">
        <h3 className="font-headline font-bold text-lg text-slate-900">Recent Alarm Triggers</h3>
        <div className="flex items-center gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
            <input type="text" value={search} onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search resources..."
              className="pl-10 pr-4 py-1.5 bg-white border border-slate-200 rounded-lg text-sm w-64 focus:ring-2 focus:ring-primary/20 outline-none" />
          </div>
          <button className="p-1.5 hover:bg-slate-100 rounded-md">
            <SlidersHorizontal size={18} className="text-slate-500" />
          </button>
        </div>
      </div>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest font-bold text-slate-500 border-b border-slate-100">
            <th className="px-8 py-4">Time</th><th className="px-6 py-4">Resource</th><th className="px-6 py-4">Type</th>
            <th className="px-6 py-4">Metric</th><th className="px-6 py-4">State</th><th className="px-8 py-4 text-right">Value/Threshold</th>
          </tr>
        </thead>
        <tbody className="text-sm">
          {paged.map((alarm, i) => (
            <tr key={alarm.id} onClick={() => router.push(`/resources/${encodeURIComponent(alarm.resource)}`)}
              className={`hover:bg-slate-50 cursor-pointer ${i % 2 === 1 ? "bg-slate-50/30" : ""}`}>
              <td className="px-8 py-4 font-mono text-xs text-slate-500">{alarm.time}</td>
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
              <td className={`px-8 py-4 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-error" : "text-slate-600"}`}>{alarm.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-8 py-4 bg-slate-50/30 border-t border-slate-100">
        <Pagination page={page} pageSize={pageSize} total={filtered.length} onPageChange={setPage} onPageSizeChange={handlePageSizeChange} />
      </div>
    </div>
  );
}
