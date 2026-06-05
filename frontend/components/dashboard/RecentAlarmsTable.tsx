"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Search, ChevronDown, ChevronRight, BellOff } from "lucide-react";
import type { Alarm } from "@/types";
import { encodeResourceId } from "@/lib/resource-id";

type SortDir = "asc" | "desc";

const COLUMNS: { key: string; label: string; align?: string }[] = [
  { key: "time", label: "Time" },
  { key: "resource", label: "Resource" },
  { key: "type", label: "Type" },
  { key: "metric", label: "Metric" },
  { key: "state", label: "State" },
  { key: "value", label: "Value/Threshold", align: "text-right" },
];

const STATE_ORDER: Record<string, number> = { ALARM: 0, INSUFFICIENT_DATA: 1, OK: 2, OFF: 3 };

const STATE_LABEL: Record<string, string> = {
  INSUFFICIENT_DATA: "INSUFFICIENT",
};

type TimeBucket = "recent" | "today" | "older";

const BUCKET_LABELS: Record<TimeBucket, string> = {
  recent: "Last hour",
  today: "Last 24 hours",
  older: "Older",
};

function getTimeBucket(timeStr: string): TimeBucket {
  const now = Date.now();
  const ts = new Date(timeStr).getTime();
  const diffMs = now - ts;
  if (diffMs < 60 * 60 * 1000) return "recent";
  if (diffMs < 24 * 60 * 60 * 1000) return "today";
  return "older";
}

function stateRing(s: string) {
  const m: Record<string, string> = {
    ALARM: "bg-error/10 text-error ring-error/20",
    INSUFFICIENT_DATA: "bg-amber-100 text-amber-700 ring-amber-500/20",
    OK: "bg-green-100 text-green-700 ring-green-500/20",
    OFF: "bg-slate-100 text-slate-500 ring-slate-400/20",
  };
  return m[s] ?? m.OFF;
}

function stateDot(s: string) {
  const m: Record<string, string> = {
    ALARM: "bg-error animate-pulse",
    INSUFFICIENT_DATA: "bg-amber-500",
    OK: "bg-green-500",
    OFF: "bg-slate-400",
  };
  return m[s] ?? m.OFF;
}

interface RecentAlarmsTableProps {
  alarms: Alarm[];
}

function AlarmRow({ alarm, onClick }: { alarm: Alarm; onClick: () => void }) {
  return (
    <tr
      onClick={onClick}
      className="hover:bg-slate-50 transition-colors cursor-pointer"
    >
      <td className="px-4 py-3 font-mono text-xs text-slate-500">{alarm.time}</td>
      <td className="px-4 py-3" title={alarm.arn}>
        <span className="font-bold text-slate-900">{alarm.resource}</span>
      </td>
      <td className="px-4 py-3">
        <span className="bg-slate-100 px-2 py-0.5 rounded text-[10px] font-bold text-slate-600">
          {alarm.type}
        </span>
      </td>
      <td className="px-4 py-3 font-medium text-slate-700">{alarm.metric}</td>
      <td className="px-4 py-3">
        <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-bold ring-1 ${stateRing(alarm.state)}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${stateDot(alarm.state)}`} />
          {STATE_LABEL[alarm.state] ?? alarm.state}
        </span>
      </td>
      <td className={`px-4 py-3 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-error" : "text-slate-600"}`}>
        {alarm.value ?? "—"}
      </td>
    </tr>
  );
}

function BucketSection({
  bucket,
  alarms,
  defaultOpen,
  onRowClick,
}: {
  bucket: TimeBucket;
  alarms: Alarm[];
  defaultOpen: boolean;
  onRowClick: (alarm: Alarm) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);

  const alarmCount = alarms.filter((a) => a.state === "ALARM").length;
  const badgeLabel = alarmCount > 0 ? `${alarmCount} ALARM` : `${alarms.length} events`;
  const badgeColor = alarmCount > 0 ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600";

  return (
    <>
      <tr
        className="bg-slate-50/70 cursor-pointer select-none hover:bg-slate-100/70 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <td colSpan={6} className="px-4 py-2">
          <span className="inline-flex items-center gap-2 text-xs font-bold text-slate-600">
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {BUCKET_LABELS[bucket]}
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${badgeColor}`}>
              {badgeLabel}
            </span>
          </span>
        </td>
      </tr>
      {open &&
        alarms.map((alarm) => (
          <AlarmRow
            key={alarm.id}
            alarm={alarm}
            onClick={() => onRowClick(alarm)}
          />
        ))}
    </>
  );
}

export function RecentAlarmsTable({ alarms }: RecentAlarmsTableProps) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [sortKey] = useState("time");
  const [sortDir] = useState<SortDir>("desc");

  const filtered = useMemo(
    () =>
      alarms.filter((a) => {
        const q = search.toLowerCase();
        return (a.resource ?? "").toLowerCase().includes(q) ||
          (a.metric ?? "").toLowerCase().includes(q);
      }),
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

  const grouped = useMemo(() => {
    const buckets: Record<TimeBucket, Alarm[]> = { recent: [], today: [], older: [] };
    for (const alarm of sorted) {
      buckets[getTimeBucket(alarm.time)].push(alarm);
    }
    return buckets;
  }, [sorted]);

  const activeBuckets = (["recent", "today", "older"] as TimeBucket[]).filter(
    (b) => grouped[b].length > 0,
  );

  const header = (
    <div className="px-8 py-6 flex justify-between items-center bg-slate-50/50">
      <h3 className="font-headline font-bold text-lg text-slate-900">Recent Alarm Triggers</h3>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search resources or metrics..."
          className="pl-10 pr-4 py-1.5 bg-white border border-slate-200 rounded-lg text-sm w-64 focus:ring-2 focus:ring-primary/20 outline-none"
        />
      </div>
    </div>
  );

  if (alarms.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
        {header}
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <BellOff size={28} className="text-slate-300 mb-3" />
          <p className="text-sm font-semibold text-slate-600">No recent alarm events</p>
          <p className="text-xs text-slate-400 mt-1">No state changes from monitored resources</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      {header}
      <table className="w-full text-sm">
        <thead className="bg-slate-50 border-b border-slate-200">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider ${col.align ?? ""}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {activeBuckets.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-400">
                No results match your search
              </td>
            </tr>
          ) : (
            activeBuckets.map((bucket) => (
              <BucketSection
                key={bucket}
                bucket={bucket}
                alarms={grouped[bucket]}
                defaultOpen={bucket !== "older"}
                onRowClick={(alarm) =>
                  router.push(`/resources/${encodeResourceId(alarm.resource)}`)
                }
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
