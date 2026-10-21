"use client";

import { useState, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Plus } from "lucide-react";
import type { DashboardStats, Alarm } from "@/types";
import { Button } from "@/components/shared/Button";
import { fetchDashboardStats } from "@/lib/api-functions";
import { StatCardGrid } from "./StatCardGrid";
import { RecentAlarmsTable } from "./RecentAlarmsTable";
import { CreateAlarmModal } from "./create-alarm/CreateAlarmModal";
import { FilterBar } from "@/components/resources/FilterBar";

const PREV_STATS_KEY = "dashboard_prev_stats";

interface CustomerDto { id: string; name: string }
interface AccountDto { id: string; name: string; customerId: string }

interface DashboardContentProps {
  stats: DashboardStats;
  alarms: Alarm[];
  customers: CustomerDto[];
  accounts: AccountDto[];
  /** 상단 글로벌 필터가 정한 범위(URL ?customer=&account=) */
  customerFilter?: string;
  accountFilter?: string;
}

export function DashboardContent({
  stats, alarms, accounts, customerFilter = "", accountFilter = "",
}: DashboardContentProps) {
  const router = useRouter();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [typeFilter, setTypeFilter] = useState("");
  const [prevStats, setPrevStats] = useState<DashboardStats | undefined>(undefined);

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(PREV_STATS_KEY);
      if (stored) setPrevStats(JSON.parse(stored) as DashboardStats);
      sessionStorage.setItem(PREV_STATS_KEY, JSON.stringify(stats));
    } catch { /* sessionStorage unavailable */ }
  }, [stats]);

  // 조회 인덱스: 알람마다 accounts 배열을 다시 훑지 않도록 한 번만 만든다 (O(n×m) → O(n)).
  const customerAccountIds = useMemo(() => {
    const map = new Map<string, Set<string>>();
    accounts.forEach((acc) => {
      if (!map.has(acc.customerId)) map.set(acc.customerId, new Set());
      map.get(acc.customerId)!.add(acc.id);
    });
    return map;
  }, [accounts]);

  const filteredAlarms = useMemo(() => {
    const customerAccounts = customerFilter ? customerAccountIds.get(customerFilter) : null;
    return alarms.filter((a) => {
      const account = a.account ?? "";
      if (accountFilter && account !== accountFilter) return false;
      if (typeFilter && a.type !== typeFilter) return false;
      if (customerFilter && !customerAccounts?.has(account)) return false;
      return true;
    });
  }, [alarms, customerFilter, accountFilter, typeFilter, customerAccountIds]);

  // 고객사·계정 필터는 서버에서 그 범위로 다시 센다 — 화면에서 일부만 다시 세면 감시 중/안 함 수가 전체 그대로 남는다.
  const [scopedStats, setScopedStats] = useState<DashboardStats | null>(null);
  useEffect(() => {
    if (!customerFilter && !accountFilter) {
      setScopedStats(null);
      return;
    }
    let cancelled = false;
    fetchDashboardStats({ customer_id: customerFilter, account_id: accountFilter })
      .then((s) => { if (!cancelled) setScopedStats(s); })
      .catch(() => { if (!cancelled) setScopedStats(null); });
    return () => { cancelled = true; };
  }, [customerFilter, accountFilter]);
  const filteredStats = scopedStats ?? stats;

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">System Overview</h1>
          <p className="text-sm text-slate-500 mt-1">Real-time health monitoring for AWS infrastructure.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={() => router.refresh()} icon={<RefreshCw size={16} />}>
            Refresh
          </Button>
          <Button variant="primary" onClick={() => setIsModalOpen(true)} icon={<Plus size={18} />}>
            Create Alarm
          </Button>
        </div>
      </header>

      <StatCardGrid
        stats={filteredStats}
        prevStats={prevStats}
        filters={{ customer_id: customerFilter, account_id: accountFilter }}
      />

      {/* Filter bar */}
      <FilterBar
        search=""
        onSearchChange={() => {}}
        typeFilter={typeFilter}
        onTypeChange={setTypeFilter}
        hideSearch
        onClearAll={() => setTypeFilter("")}
      />

      <RecentAlarmsTable alarms={filteredAlarms} />

      <CreateAlarmModal open={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => router.refresh()} />
    </div>
  );
}
