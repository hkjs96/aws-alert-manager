import { Suspense } from "react";
import { computeDashboardStats, getAlarms } from "@/lib/mock-store";
import { DashboardContent } from "@/components/dashboard/DashboardContent";
import { Skeleton } from "@/components/shared/Skeleton";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard | Alarm Manager",
  description: "System overview and real-time health monitoring for AWS infrastructure.",
};

// When real backend API is ready, replace mock imports with:
// import { fetchDashboardStats, fetchRecentAlarms } from "@/lib/api-functions";

export default async function DashboardPage() {
  // Pragmatic approach: use mock data directly for now.
  // When the real backend API is ready, swap to:
  //   const [stats, alarmsRes] = await Promise.all([
  //     fetchDashboardStats({}),
  //     fetchRecentAlarms({}, { page: 1, page_size: 25 }),
  //   ]);
  const stats = computeDashboardStats();
  const alarms = getAlarms();

  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardContent stats={stats} alarms={alarms} />
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
