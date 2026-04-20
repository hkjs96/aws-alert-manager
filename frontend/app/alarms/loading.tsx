import { Skeleton } from "@/components/shared/Skeleton";

export default function AlarmsLoading() {
  return (
    <div className="space-y-8">
      {/* Title skeleton */}
      <div className="flex justify-between items-end">
        <div>
          <div className="h-8 w-48 bg-slate-100 animate-pulse rounded" />
          <div className="h-4 w-80 bg-slate-100 animate-pulse rounded mt-2" />
        </div>
        <div className="flex gap-3">
          <div className="h-10 w-64 bg-slate-100 animate-pulse rounded-lg" />
          <div className="h-10 w-36 bg-slate-100 animate-pulse rounded-lg" />
        </div>
      </div>

      {/* Summary card skeletons */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} variant="card" />
        ))}
      </div>

      {/* Filter tabs skeleton */}
      <div className="h-10 w-96 bg-slate-100 animate-pulse rounded-xl" />

      {/* Table skeleton */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <Skeleton variant="table-row" count={8} />
      </div>
    </div>
  );
}
