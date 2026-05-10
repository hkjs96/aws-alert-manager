import { Skeleton } from "@/components/shared/Skeleton";

export default function DashboardLoading() {
  return (
    <div className="space-y-8">
      {/* Title skeleton */}
      <div>
        <div className="h-8 w-48 bg-slate-100 animate-pulse rounded" />
        <div className="h-4 w-72 bg-slate-100 animate-pulse rounded mt-2" />
      </div>

      {/* 4 stat card skeletons in matching grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} variant="card" />
        ))}
      </div>

      {/* 6 table row skeletons */}
      <Skeleton variant="table-row" count={6} />
    </div>
  );
}
