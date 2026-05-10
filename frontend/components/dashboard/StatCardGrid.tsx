import type { DashboardStats } from "@/types";

interface StatCardGridProps {
  stats: DashboardStats;
  prevStats?: DashboardStats;
}

interface StatCardDef {
  label: string;
  valueKey: keyof DashboardStats;
  accentColor: string;
  numColor: string;
  statusFn: (v: number) => { text: string; color: string };
  badWhenHigh: boolean;
}

const STAT_CARDS: StatCardDef[] = [
  {
    label: "Monitored Resources",
    valueKey: "monitored_count",
    accentColor: "border-slate-400",
    numColor: "text-slate-700",
    statusFn: () => ({ text: "Tag: Monitoring=on", color: "text-slate-400" }),
    badWhenHigh: false,
  },
  {
    label: "Active Alarms",
    valueKey: "active_alarms",
    accentColor: "border-red-500",
    numColor: "text-red-600",
    statusFn: (v) => v > 0
      ? ({ text: "Requires attention", color: "text-red-500" })
      : ({ text: "All clear", color: "text-green-600" }),
    badWhenHigh: true,
  },
  {
    label: "Unmonitored",
    valueKey: "unmonitored_count",
    accentColor: "border-amber-500",
    numColor: "text-amber-600",
    statusFn: (v) => v > 0
      ? ({ text: "Action needed", color: "text-amber-600" })
      : ({ text: "All monitored", color: "text-green-600" }),
    badWhenHigh: true,
  },
  {
    label: "Accounts",
    valueKey: "account_count",
    accentColor: "border-blue-500",
    numColor: "text-blue-600",
    statusFn: () => ({ text: "All connected", color: "text-green-600" }),
    badWhenHigh: false,
  },
];

function DeltaBadge({ diff, badWhenHigh }: { diff: number; badWhenHigh: boolean }) {
  if (diff === 0) {
    return <span className="text-[10px] font-semibold text-slate-400">→ No change</span>;
  }
  const increased = diff > 0;
  const isBad = badWhenHigh ? increased : !increased;
  const color = isBad ? "text-amber-600" : "text-green-600";
  const arrow = increased ? "↑" : "↓";
  const sign = increased ? "+" : "";
  return (
    <span className={`text-[10px] font-semibold ${color}`}>
      {arrow} {sign}{diff} from last visit
    </span>
  );
}

export function StatCardGrid({ stats, prevStats }: StatCardGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
      {STAT_CARDS.map((card) => {
        const value = stats[card.valueKey];
        const prev = prevStats?.[card.valueKey];
        const status = card.statusFn(value);
        const diff = prev !== undefined ? value - prev : undefined;

        return (
          <div
            key={card.label}
            className={`bg-white rounded-xl shadow-soft border border-slate-200 border-l-4 ${card.accentColor}`}
          >
            <div className="px-5 py-5">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-3">
                {card.label}
              </p>
              <p className={`text-4xl font-bold font-mono ${card.numColor}`}>
                {value}
              </p>
              <p className={`text-[11px] font-semibold mt-2 ${status.color}`}>
                {status.text}
              </p>
              {diff !== undefined && (
                <div className="mt-1.5">
                  <DeltaBadge diff={diff} badWhenHigh={card.badWhenHigh} />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
