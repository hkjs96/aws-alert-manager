import { Skeleton } from "@/components/shared/Skeleton";

export default function CustomersLoading() {
  return (
    <div className="space-y-8">
      <div>
        <div className="h-8 w-64 bg-slate-100 animate-pulse rounded" />
        <div className="h-4 w-96 bg-slate-100 animate-pulse rounded mt-2" />
      </div>
      <div className="grid grid-cols-12 gap-8">
        <div className="col-span-12 lg:col-span-5">
          <Skeleton variant="card" count={1} />
        </div>
        <div className="col-span-12 lg:col-span-7">
          <Skeleton variant="table-row" count={4} />
        </div>
      </div>
    </div>
  );
}
