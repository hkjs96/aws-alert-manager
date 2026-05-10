'use client';

import { ErrorPanel } from "@/components/shared/ErrorPanel";

interface DashboardErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DashboardError({ error, reset }: DashboardErrorProps) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          System Overview
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Real-time health monitoring for AWS infrastructure.
        </p>
      </div>

      <ErrorPanel message={error.message} onRetry={reset} />
    </div>
  );
}
