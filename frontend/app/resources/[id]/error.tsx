"use client";

import { ErrorPanel } from "@/components/shared/ErrorPanel";

interface ResourceDetailErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ResourceDetailError({ error, reset }: ResourceDetailErrorProps) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          Resource Detail
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Alarm configuration and monitoring for this resource.
        </p>
      </div>

      <ErrorPanel message={error.message} onRetry={reset} />
    </div>
  );
}
