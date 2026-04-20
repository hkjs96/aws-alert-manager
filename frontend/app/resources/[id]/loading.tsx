import { Skeleton } from "@/components/shared/Skeleton";

export default function ResourceDetailLoading() {
  return (
    <div className="space-y-8">
      {/* Header skeleton */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <div className="h-4 w-40 bg-slate-100 animate-pulse rounded mb-2" />
          <div className="h-8 w-64 bg-slate-100 animate-pulse rounded" />
          <div className="mt-4 flex gap-3">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="h-8 w-32 bg-slate-100 animate-pulse rounded-lg" />
            ))}
          </div>
        </div>
        <div className="h-20 w-64 bg-slate-100 animate-pulse rounded-xl" />
      </div>

      {/* Alarm config table skeleton */}
      <div className="bg-slate-50 rounded-xl border border-slate-200 p-4">
        <div className="h-6 w-48 bg-slate-200 animate-pulse rounded mb-4" />
        <Skeleton variant="table-row" count={6} />
      </div>

      {/* Bottom cards skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Skeleton variant="card" />
        <div className="md:col-span-2">
          <Skeleton variant="card" />
        </div>
      </div>
    </div>
  );
}
