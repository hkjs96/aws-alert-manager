import type { ReactElement } from 'react';

type SkeletonVariant = 'card' | 'table-row' | 'text';

interface SkeletonProps {
  variant: SkeletonVariant;
  count?: number;
}

function SkeletonCard() {
  return <div className="rounded-xl bg-slate-100 animate-pulse h-32" />;
}

function SkeletonTableRow() {
  return (
    <div className="flex gap-4 py-3">
      <div className="h-4 bg-slate-100 animate-pulse rounded w-1/4" />
      <div className="h-4 bg-slate-100 animate-pulse rounded w-1/3" />
      <div className="h-4 bg-slate-100 animate-pulse rounded w-1/6" />
      <div className="h-4 bg-slate-100 animate-pulse rounded w-1/4" />
    </div>
  );
}

function SkeletonText() {
  return <div className="h-4 bg-slate-100 animate-pulse rounded w-3/4" />;
}

const VARIANT_MAP: Record<SkeletonVariant, () => ReactElement> = {
  card: SkeletonCard,
  'table-row': SkeletonTableRow,
  text: SkeletonText,
};

export function Skeleton({ variant, count = 1 }: SkeletonProps) {
  const Component = VARIANT_MAP[variant];
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: count }, (_, i) => (
        <Component key={i} />
      ))}
    </div>
  );
}
