"use client";

import { ErrorPanel } from "@/components/shared/ErrorPanel";

interface AlarmsErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function AlarmsError({ error, reset }: AlarmsErrorProps) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          Active Alarms
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Comprehensive list of all triggered and monitored alarm states.
        </p>
      </div>

      <ErrorPanel message={error.message} onRetry={reset} />
    </div>
  );
}
