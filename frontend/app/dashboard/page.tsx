import { Suspense } from "react";
import { fetchDashboardStats, fetchAlarms, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { DashboardContent } from "@/components/dashboard/DashboardContent";
import { Skeleton } from "@/components/shared/Skeleton";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard | Alarm Manager",
  description: "System overview and real-time health monitoring for AWS infrastructure.",
};

export default async function DashboardPage() {
  let stats, alarms, customers, accounts;
  try {
    [stats, alarms, customers, accounts] = await Promise.all([
      fetchDashboardStats(),
      fetchAlarms(),
      fetchCustomerOptions(),
      fetchAccountOptions(),
    ]);
  } catch (error) {
    console.error("[DashboardPage] Failed to fetch data:", error);
    // Fallback values to prevent crash
    stats = { total_resources: 0, active_alarms: 0, unmonitored_resources: 0, connected_accounts: 0 };
    alarms = [];
    customers = [];
    accounts = [];
  }

  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardContent stats={stats} alarms={alarms} customers={customers} accounts={accounts} />
    </Suspense>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8">
      <div>
        <div className="h-8 w-48 bg-slate-100 animate-pulse rounded" />
        <div className="h-4 w-72 bg-slate-100 animate-pulse rounded mt-2" />
      </div>
      <Skeleton variant="card" count={4} />
      <Skeleton variant="table-row" count={6} />
    </div>
  );
}
