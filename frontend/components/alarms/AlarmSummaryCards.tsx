import type { AlarmSummary } from "@/types/api";

interface AlarmSummaryCardsProps {
  summary: AlarmSummary;
}

const SEGMENTS = [
  { key: "alarm_count" as const, label: "ALARM", barColor: "bg-red-500", textColor: "text-red-600", dotColor: "bg-red-500" },
  { key: "ok_count" as const, label: "OK", barColor: "bg-green-500", textColor: "text-green-600", dotColor: "bg-green-500" },
  { key: "insufficient_count" as const, label: "INSUFFICIENT", barColor: "bg-amber-500", textColor: "text-amber-600", dotColor: "bg-amber-500" },
] as const;

export function AlarmSummaryCards({ summary }: AlarmSummaryCardsProps) {
  const { total, alarm_count, ok_count, insufficient_count } = summary;
  const off_count = Math.max(0, total - alarm_count - ok_count - insufficient_count);

  const allSegments = [
    ...SEGMENTS,
    { key: "off" as const, label: "OFF", barColor: "bg-slate-200", textColor: "text-slate-400", dotColor: "bg-slate-300" },
  ];

  const counts: Record<string, number> = { alarm_count, ok_count, insufficient_count, off: off_count };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm px-6 py-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Alarm Health
        </span>
        <span className="text-sm font-extrabold text-slate-700">
          {total} total
        </span>
      </div>

      {total === 0 ? (
        <div className="h-2.5 bg-slate-100 rounded-full" />
      ) : (
        <div className="flex h-2.5 rounded-full overflow-hidden gap-px">
          {allSegments.map(({ key, label, barColor }) => {
            const count = counts[key] ?? 0;
            if (count === 0) return null;
            return (
              <div
                key={label}
                title={`${label}: ${count}`}
                className={`${barColor} transition-all`}
                style={{ flex: count }}
              />
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-5 mt-3 flex-wrap">
        {allSegments.map(({ key, label, textColor, dotColor }) => {
          const count = counts[key] ?? 0;
          return (
            <span key={label} className={`inline-flex items-center gap-1.5 text-[11px] font-bold ${textColor}`}>
              <span className={`w-2 h-2 rounded-sm inline-block ${dotColor}`} />
              {count} {label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
