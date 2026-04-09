"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Plus } from "lucide-react";
import type { DashboardStats } from "@/types";
import type { Alarm } from "@/types";
import { StatCardGrid } from "./StatCardGrid";
import { RecentAlarmsTable } from "./RecentAlarmsTable";
import { CreateAlarmModal } from "./create-alarm/CreateAlarmModal";

interface DashboardContentProps {
  stats: DashboardStats;
  alarms: Alarm[];
}

export function DashboardContent({ stats, alarms }: DashboardContentProps) {
  const router = useRouter();
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
            System Overview
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Real-time health monitoring for AWS infrastructure.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => router.refresh()}
            className="px-4 py-2 bg-white text-slate-700 text-sm font-semibold rounded-lg shadow-sm border border-slate-200 hover:bg-slate-50 flex items-center gap-2"
          >
            <RefreshCw size={16} /> Refresh Metrics
          </button>
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg shadow-lg shadow-primary/20 flex items-center gap-2"
          >
            <Plus size={18} /> Create Alarm
          </button>
        </div>
      </div>

      <StatCardGrid stats={stats} />
      <RecentAlarmsTable alarms={alarms} />

      <CreateAlarmModal
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={() => router.refresh()}
      />
    </div>
  );
}
