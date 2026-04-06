import type { RecentAlarm } from "@/types";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { AlarmStatusPill } from "@/components/shared/AlarmStatusPill";

interface RecentAlarmsTableProps {
  alarms: RecentAlarm[];
  loading?: boolean;
}

export function RecentAlarmsTable({ alarms, loading = false }: RecentAlarmsTableProps) {
  if (loading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3">
          <div className="h-4 w-48 animate-pulse rounded bg-slate-100" />
        </div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4 border-b border-slate-50 px-4 py-3">
            {Array.from({ length: 6 }).map((_, j) => (
              <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-100 px-4 py-3">
        <h3 className="text-sm font-medium text-slate-700">최근 알람 트리거</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2">시간</th>
              <th className="px-4 py-2">리소스</th>
              <th className="px-4 py-2">유형</th>
              <th className="px-4 py-2">메트릭</th>
              <th className="px-4 py-2">등급</th>
              <th className="px-4 py-2">상태</th>
              <th className="px-4 py-2 text-right">값 / 임계치</th>
            </tr>
          </thead>
          <tbody>
            {alarms.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                  최근 알람 트리거가 없습니다.
                </td>
              </tr>
            ) : (
              alarms.map((alarm, i) => (
                <tr key={`${alarm.resource_id}-${alarm.timestamp}`} className={i % 2 === 1 ? "bg-slate-50/50" : ""}>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-500">{alarm.timestamp}</td>
                  <td className="px-4 py-2">
                    <span className="font-mono text-xs">{alarm.resource_id}</span>
                  </td>
                  <td className="px-4 py-2">{alarm.resource_type}</td>
                  <td className="px-4 py-2">{alarm.metric}</td>
                  <td className="px-4 py-2"><SeverityBadge severity={alarm.severity} /></td>
                  <td className="px-4 py-2"><AlarmStatusPill state="ALARM" /></td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-red-600">
                    {alarm.value} / {alarm.threshold}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
