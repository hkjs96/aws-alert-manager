"use client";

import { ErrorPanel } from "@/components/shared/ErrorPanel";

interface ResourcesErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ResourcesError({ error, reset }: ResourcesErrorProps) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          Resources Inventory
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Manage and monitor AWS entities across all registered accounts.
        </p>
      </div>

      <ErrorPanel message={error.message} onRetry={reset} />
    </div>
  );
}
