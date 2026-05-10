import { Skeleton } from "@/components/shared/Skeleton";

export default function ResourcesLoading() {
  return (
    <div className="space-y-8">
      {/* Title skeleton */}
      <div className="flex justify-between items-end">
        <div>
          <div className="h-8 w-56 bg-slate-100 animate-pulse rounded" />
          <div className="h-4 w-80 bg-slate-100 animate-pulse rounded mt-2" />
        </div>
        <div className="flex gap-3">
          <div className="h-10 w-32 bg-slate-100 animate-pulse rounded-xl" />
          <div className="h-10 w-40 bg-slate-100 animate-pulse rounded-xl" />
        </div>
      </div>

      {/* Filter bar skeleton */}
      <div className="bg-slate-100 rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="space-y-1">
            <div className="h-3 w-16 bg-slate-200 animate-pulse rounded" />
            <div className="h-9 bg-white animate-pulse rounded-lg" />
          </div>
        ))}
      </div>

      {/* Table skeleton */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <Skeleton variant="table-row" count={8} />
      </div>
    </div>
  );
}
