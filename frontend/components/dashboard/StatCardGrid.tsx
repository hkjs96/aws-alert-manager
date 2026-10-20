import Link from "next/link";

import type { DashboardStats } from "@/types";

interface StatCardGridProps {
  stats: DashboardStats;
  prevStats?: DashboardStats;
  /** 지금 걸린 고객사·계정 필터 — 카드 링크에 실어 보낸다. 필터가 있으면 "지난 방문 대비"는 숨긴다(범위가 달라 비교가 틀린다). */
  filters?: { customer_id?: string; account_id?: string };
}

type Tone = { num: string; sub: string };

interface CardView {
  label: string;
  value: number;
  sub: string;
  tone: Tone;
  href: string;
  cta: string;
  deltaKey?: keyof DashboardStats;
  badWhenHigh?: boolean;
}

// 색은 상태가 나쁠 때만 쓴다. 평소에는 회색, 링크만 primary.
const NEUTRAL: Tone = { num: "text-slate-700", sub: "text-slate-500" };
const DANGER: Tone = { num: "text-red-600", sub: "text-red-600" };

function withFilters(path: string, filters: StatCardGridProps["filters"]): string {
  const [base = path, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (filters?.customer_id) params.set("customer", filters.customer_id);
  if (filters?.account_id) params.set("account", filters.account_id);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export function buildCards(stats: DashboardStats): CardView[] {
  const total = stats.monitored_count + stats.unmonitored_count;
  const ours = stats.active_alarms_ours ?? stats.active_alarms;
  const customer = stats.active_alarms_customer;
  const connected = stats.accounts_connected ?? stats.account_count;
  const failed = stats.accounts_failed ?? 0;
  return [
    {
      label: "Monitored Resources",
      value: stats.monitored_count,
      sub: `리소스 ${total.toLocaleString()}개 중`,
      tone: NEUTRAL,
      href: "/resources?monitoring=on",
      cta: "리소스 보기 →",
      deltaKey: "monitored_count",
    },
    {
      label: "Active Alarms",
      value: stats.active_alarms,
      // 고객 알람 수를 모르면(실시간 조회 실패) 나누지 않는다 — 0으로 보이면 "All clear"로 오해한다
      sub: customer == null ? "고객 알람 확인 불가" : stats.active_alarms ? `우리 ${ours} · 고객 ${customer}` : "All clear",
      tone: stats.active_alarms ? DANGER : NEUTRAL,
      href: "/alarms?state=ALARM",
      cta: "알람 보기 →",
      deltaKey: "active_alarms",
      badWhenHigh: true,
    },
    {
      label: "Unmonitored",
      value: stats.unmonitored_count,
      // 고객이 고른 리소스만 감시하는 게 정상 운영이다 — 경고가 아니다
      sub: "켤 수 있는 리소스",
      tone: { num: "text-slate-500", sub: "text-slate-500" },
      href: "/resources?monitoring=off",
      cta: "리소스 보기 →",
      deltaKey: "unmonitored_count",
    },
    {
      label: "Accounts",
      value: stats.account_count,
      sub: `연결 ${connected} · 실패 ${failed}`,
      tone: failed ? DANGER : NEUTRAL,
      href: "/customers",
      cta: "계정 관리 →",
    },
  ];
}

function DeltaBadge({ diff, badWhenHigh }: { diff: number; badWhenHigh: boolean }) {
  if (diff === 0) {
    return <span className="text-[10px] font-semibold text-slate-400">→ No change</span>;
  }
  const increased = diff > 0;
  const isBad = badWhenHigh ? increased : false;
  const color = isBad ? "text-amber-600" : "text-slate-500";
  return (
    <span className={`text-[10px] font-semibold ${color}`}>
      {increased ? "↑" : "↓"} {increased ? "+" : ""}{diff} from last visit
    </span>
  );
}

export function StatCardGrid({ stats, prevStats, filters }: StatCardGridProps) {
  const filtered = Boolean(filters?.customer_id || filters?.account_id);
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
      {buildCards(stats).map((card) => {
        const prev = card.deltaKey ? prevStats?.[card.deltaKey] : undefined;
        const diff = !filtered && typeof prev === "number" ? card.value - prev : undefined;
        return (
          <Link
            key={card.label}
            href={withFilters(card.href, filters)}
            className="flex flex-col rounded-xl border border-l-4 border-slate-200 bg-white px-5 py-5 shadow-soft transition-colors hover:border-slate-400"
          >
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">
              {card.label}
            </p>
            <p className={`font-mono text-4xl font-bold ${card.tone.num}`}>{card.value}</p>
            <p className={`mt-2 text-[11px] font-semibold ${card.tone.sub}`}>{card.sub}</p>
            {diff !== undefined && (
              <div className="mt-1.5">
                <DeltaBadge diff={diff} badWhenHigh={card.badWhenHigh ?? false} />
              </div>
            )}
            <p className="mt-3 text-[11px] font-semibold text-primary">{card.cta}</p>
          </Link>
        );
      })}
    </div>
  );
}
