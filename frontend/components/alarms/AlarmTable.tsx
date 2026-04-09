"use client";

import { useRouter } from "next/navigation";
import { ExternalLink, MoreVertical } from "lucide-react";
import type { Alarm } from "@/types";

interface AlarmTableProps {
  alarms: Alarm[];
}

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

export function AlarmTable({ alarms }: AlarmTableProps) {
  const router = useRouter();

  return (
    <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200 shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest font-bold text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-8 py-4">Time</th>
              <th className="px-6 py-4">Resource</th>
              <th className="px-6 py-4">Metric</th>
              <th className="px-6 py-4">State</th>
              <th className="px-8 py-4 text-right">Value</th>
              <th className="px-8 py-4 text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {alarms.map((alarm, i) => (
              <tr
                key={alarm.id}
                className={`hover:bg-slate-50 transition-colors ${i % 2 === 1 ? "bg-slate-50/30" : ""}`}
              >
                <td className="px-8 py-4 font-mono text-xs text-slate-500">
                  {alarm.time}
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-col">
                    <span className="font-bold text-slate-900">{alarm.resource}</span>
                    <span className="text-[10px] font-mono text-slate-400">{alarm.arn}</span>
                  </div>
                </td>
                <td className="px-6 py-4 font-medium text-slate-700">{alarm.metric}</td>
                <td className="px-6 py-4">
                  <StateBadge state={alarm.state} />
                </td>
                <td
                  className={`px-8 py-4 text-right font-mono font-bold ${alarm.state === "ALARM" ? "text-error" : "text-slate-600"}`}
                >
                  {alarm.value}
                </td>
                <td className="px-8 py-4 text-center">
                  <div className="flex justify-center gap-2">
                    <button
                      onClick={() =>
                        router.push(`/resources/${encodeURIComponent(alarm.resource)}`)
                      }
                      className="p-1.5 hover:bg-slate-200 rounded-md text-slate-500 transition-colors"
                    >
                      <ExternalLink size={16} />
                    </button>
                    <button className="p-1.5 hover:bg-slate-200 rounded-md text-slate-500 transition-colors">
                      <MoreVertical size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-bold ring-1 ${STATE_STYLES[state] ?? STATE_STYLES.OFF}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${DOT_STYLES[state] ?? DOT_STYLES.OFF}`} />
      {state}
    </span>
  );
}
