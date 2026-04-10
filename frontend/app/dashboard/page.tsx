import { Suspense } from "react";
import { computeDashboardStats, getAlarms } from "@/lib/mock-store";
import { MOCK_CUSTOMERS, MOCK_ACCOUNTS } from "@/lib/mock-data";
import { DashboardContent } from "@/components/dashboard/DashboardContent";
import { Skeleton } from "@/components/shared/Skeleton";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard | Alarm Manager",
  description: "System overview and real-time health monitoring for AWS infrastructure.",
};

export default async function DashboardPage() {
  const stats = computeDashboardStats();
  const alarms = getAlarms();

  const customers = MOCK_CUSTOMERS.map((c) => ({ id: c.customer_id, name: c.name }));
  const accounts = MOCK_ACCOUNTS.map((a) => ({ id: a.account_id, name: a.name, customerId: a.customer_id }));

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
