"use client";

import { Monitor, AlertTriangle, EyeOff, Server } from "lucide-react";
import { StatCard } from "@/components/dashboard/StatCard";
import { RecentAlarmsTable } from "@/components/dashboard/RecentAlarmsTable";
import type { DashboardStats, RecentAlarm } from "@/types";

// TODO: Replace with API calls
const MOCK_STATS: DashboardStats = {
  monitored_count: 1102,
  active_alarms: 14,
  unmonitored_count: 26,
  account_count: 8,
};

const MOCK_RECENT_ALARMS: RecentAlarm[] = [
  {
    timestamp: "3분 전",
    resource_id: "i-0a1b2c3d4e5f6789",
    resource_name: "web-server-prod-01",
    resource_type: "EC2",
    metric: "Disk (/)",
    severity: "SEV-3",
    state_change: "OK → ALARM",
    value: 97.2,
    threshold: 80,
  },
  {
    timestamp: "12분 전",
    resource_id: "db-XYZ9908821-RDS",
    resource_name: "auth-db-postgres",
    resource_type: "RDS",
    metric: "FreeMemoryGB",
    severity: "SEV-3",
    state_change: "OK → ALARM",
    value: 1.2,
    threshold: 2,
  },
];

export default function DashboardPage() {
  const stats = MOCK_STATS;
  const recentAlarms = MOCK_RECENT_ALARMS;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Dashboard</h1>

      <div className="grid grid-cols-4 gap-4">
        <StatCard
          title="모니터링 리소스"
          value={stats.monitored_count.toLocaleString()}
          icon={<Monitor size={20} />}
        />
        <StatCard
          title="활성 알람"
          value={stats.active_alarms}
          icon={<AlertTriangle size={20} />}
          highlight={stats.active_alarms > 0}
          subtitle={stats.active_alarms > 0 ? `${stats.active_alarms}건 확인 필요` : undefined}
        />
        <StatCard
          title="미모니터링 리소스"
          value={stats.unmonitored_count}
          icon={<EyeOff size={20} />}
        />
        <StatCard
          title="등록 어카운트"
          value={stats.account_count}
          icon={<Server size={20} />}
        />
      </div>

      <RecentAlarmsTable alarms={recentAlarms} />
    </div>
  );
}
