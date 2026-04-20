import type { DashboardStats } from "@/types";

interface StatCardGridProps {
  stats: DashboardStats;
}

interface SparklineProps {
  points: number[];
  color: string;   // stroke hex
  fill: string;    // fill hex (semi-transparent)
}

function Sparkline({ points, color, fill }: SparklineProps) {
  const W = 120;
  const H = 32;
  const PAD = 3;

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  const xs = points.map((_, i) => PAD + (i / (points.length - 1)) * (W - PAD * 2));
  const ys = points.map((p) => PAD + (1 - (p - min) / range) * (H - PAD * 2));

  const linePts = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  // area polygon: line + close bottom
  const areaPts = [
    ...xs.map((x, i) => `${x},${ys[i]}`),
    `${xs[xs.length - 1]},${H}`,
    `${xs[0]},${H}`,
  ].join(" ");

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="w-full">
      <polygon points={areaPts} fill={fill} />
      <polyline
        points={linePts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface StatCardDef {
  label: string;
  valueKey: keyof DashboardStats;
  accentColor: string;     // border-l color class
  numColor: string;        // number text color class
  trend: { delta: number; positive: boolean };
  statusFn: (v: number) => { text: string; color: string };
  spark: { points: number[]; stroke: string; fill: string };
}

const STAT_CARDS: StatCardDef[] = [
  {
    label: "Monitored Resources",
    valueKey: "monitored_count",
    accentColor: "border-blue-500",
    numColor: "text-blue-600",
    trend: { delta: 2, positive: true },
    statusFn: () => ({ text: "▲ +2 vs 어제", color: "text-green-600" }),
    spark: {
      points: [6, 7, 8, 8, 9, 10, 12],
      stroke: "#2563eb",
      fill: "rgba(37,99,235,0.08)",
    },
  },
  {
    label: "Active Alarms",
    valueKey: "active_alarms",
    accentColor: "border-red-500",
    numColor: "text-red-600",
    trend: { delta: 1, positive: false },
    statusFn: (v) => v > 0
      ? ({ text: "▲ +1 vs 어제", color: "text-red-500" })
      : ({ text: "이상 없음", color: "text-green-600" }),
    spark: {
      points: [2, 3, 2, 4, 3, 5, 4],
      stroke: "#dc2626",
      fill: "rgba(220,38,38,0.07)",
    },
  },
  {
    label: "Unmonitored",
    valueKey: "unmonitored_count",
    accentColor: "border-amber-500",
    numColor: "text-amber-600",
    trend: { delta: 0, positive: false },
    statusFn: (v) => v > 0
      ? ({ text: "⚠ 조치 필요", color: "text-amber-600" })
      : ({ text: "✓ 이상 없음", color: "text-green-600" }),
    spark: {
      points: [5, 4, 4, 3, 3, 2, 2],
      stroke: "#d97706",
      fill: "rgba(217,119,6,0.08)",
    },
  },
  {
    label: "Accounts",
    valueKey: "account_count",
    accentColor: "border-purple-500",
    numColor: "text-purple-600",
    trend: { delta: 0, positive: true },
    statusFn: () => ({ text: "✓ 모두 연결됨", color: "text-green-600" }),
    spark: {
      points: [4, 4, 4, 4, 4, 4, 4],
      stroke: "#7c3aed",
      fill: "rgba(124,58,237,0.07)",
    },
  },
];

export function StatCardGrid({ stats }: StatCardGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
      {STAT_CARDS.map((card) => {
        const value = stats[card.valueKey];
        const status = card.statusFn(value);

        return (
          <div
            key={card.label}
            className={`bg-white rounded-xl shadow-soft border border-slate-200 border-l-4 ${card.accentColor} overflow-hidden`}
          >
            {/* 상단 정보 영역 */}
            <div className="px-5 pt-5 pb-3">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-2">
                {card.label}
              </p>
              <p className={`text-4xl font-bold font-mono ${card.numColor}`}>
                {value}
              </p>
              <p className={`text-[11px] font-semibold mt-2 ${status.color}`}>
                {status.text}
              </p>
            </div>

            {/* 스파크라인 영역 — 카드 하단에 꽉 채움 */}
            <div className="px-0 pb-0">
              <Sparkline
                points={card.spark.points}
                color={card.spark.stroke}
                fill={card.spark.fill}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
