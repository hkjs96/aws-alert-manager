import { AlertTriangle, Globe } from "lucide-react";
import type { DashboardStats } from "@/types";

interface StatCardGridProps {
  stats: DashboardStats;
}

interface StatCardDef {
  label: string;
  valueKey: keyof DashboardStats;
  format?: (v: number) => string;
  color: string;
  change?: string;
  sub?: string;
  warning?: boolean;
  bars?: boolean;
  hasIcon?: boolean;
}

const STAT_CARDS: StatCardDef[] = [
  {
    label: "Monitored Resources",
    valueKey: "monitored_count",
    format: (v) => v.toLocaleString(),
    color: "border-primary",
    change: "+12%",
  },
  {
    label: "Active Alarms",
    valueKey: "active_alarms",
    color: "border-error",
    sub: "Critical state requires attention",
    warning: true,
  },
  {
    label: "Unmonitored",
    valueKey: "unmonitored_count",
    color: "border-tertiary",
    sub: "resources",
    bars: true,
  },
  {
    label: "Accounts",
    valueKey: "account_count",
    color: "border-slate-400",
    sub: "Across 12 global regions",
    hasIcon: true,
  },
];

export function StatCardGrid({ stats }: StatCardGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
      {STAT_CARDS.map((card) => {
        const value = stats[card.valueKey];
        const display = card.format ? card.format(value) : String(value);

        return (
          <div
            key={card.label}
            className={`bg-white p-8 rounded-xl shadow-sm border-l-4 ${card.color} shadow-soft`}
          >
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">
              {card.label}
            </p>
            <div className="flex items-baseline gap-2">
              <span
                className={`text-3xl font-mono font-bold ${card.warning ? "text-error" : "text-slate-900"}`}
              >
                {display}
              </span>
              {card.change && (
                <span className="text-green-600 text-xs font-bold">{card.change}</span>
              )}
              {card.warning && <AlertTriangle size={18} className="text-error" />}
              {card.hasIcon && <Globe size={18} className="text-slate-400" />}
            </div>
            {card.sub && (
              <p className="text-[10px] text-slate-400 mt-2 font-medium">{card.sub}</p>
            )}
            {card.bars ? (
              <div className="mt-4 flex gap-1">
                <div className="h-1 flex-1 bg-tertiary/20 rounded-full overflow-hidden">
                  <div className="h-full bg-tertiary w-full" />
                </div>
                <div className="h-1 flex-1 bg-tertiary/20 rounded-full overflow-hidden">
                  <div className="h-full bg-tertiary w-2/3" />
                </div>
                <div className="h-1 flex-1 bg-slate-100 rounded-full" />
              </div>
            ) : !card.sub ? (
              <div className="mt-4 h-1 w-full bg-slate-100 rounded-full overflow-hidden">
                <div className="bg-primary h-full w-[84%]" />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
