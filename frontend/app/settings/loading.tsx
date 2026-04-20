import { Skeleton } from "@/components/shared/Skeleton";

export default function SettingsLoading() {
  return (
    <div className="space-y-8">
      {/* Title skeleton */}
      <div>
        <div className="h-10 w-56 bg-slate-100 animate-pulse rounded" />
        <div className="h-4 w-96 bg-slate-100 animate-pulse rounded mt-2" />
      </div>

      <div className="grid grid-cols-12 gap-8">
        {/* Customer section skeleton */}
        <div className="col-span-12 lg:col-span-5">
          <div className="bg-white rounded-xl p-8 border border-slate-200">
            <div className="h-6 w-40 bg-slate-100 animate-pulse rounded mb-6" />
            <Skeleton variant="table-row" count={3} />
          </div>
        </div>

        {/* Account section skeleton */}
        <div className="col-span-12 lg:col-span-7">
          <div className="bg-white rounded-xl p-8 border border-slate-200">
            <div className="h-6 w-48 bg-slate-100 animate-pulse rounded mb-6" />
            <Skeleton variant="table-row" count={4} />
          </div>
        </div>
      </div>

      {/* Threshold section skeleton */}
      <div className="bg-white rounded-xl p-8 border border-slate-200">
        <div className="h-6 w-48 bg-slate-100 animate-pulse rounded mb-6" />
        <div className="flex gap-2 mb-6">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-8 w-16 bg-slate-100 animate-pulse rounded-lg" />
          ))}
        </div>
        <Skeleton variant="table-row" count={4} />
      </div>
    </div>
  );
}
