import { AlertTriangle, CheckCircle, HelpCircle, Bell } from "lucide-react";
import type { AlarmSummary } from "@/types/api";

interface AlarmSummaryCardsProps {
  summary: AlarmSummary;
}

const CARDS = [
  { key: "total" as const, label: "Total Alarms", icon: Bell, color: "text-slate-600", bg: "bg-slate-50" },
  { key: "alarm_count" as const, label: "ALARM", icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
  { key: "ok_count" as const, label: "OK", icon: CheckCircle, color: "text-green-600", bg: "bg-green-50" },
  { key: "insufficient_count" as const, label: "INSUFFICIENT", icon: HelpCircle, color: "text-amber-600", bg: "bg-amber-50" },
] as const;

export function AlarmSummaryCards({ summary }: AlarmSummaryCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      {CARDS.map(({ key, label, icon: Icon, color, bg }) => (
        <div
          key={key}
          className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex items-center gap-4"
        >
          <div className={`p-2.5 rounded-lg ${bg}`}>
            <Icon className={`w-5 h-5 ${color}`} />
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
              {label}
            </p>
            <p className={`text-2xl font-extrabold ${color}`}>
              {summary[key]}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
