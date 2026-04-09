"use client";

import { ErrorPanel } from "@/components/shared/ErrorPanel";

interface SettingsErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function SettingsError({ error, reset }: SettingsErrorProps) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-4xl font-headline font-semibold tracking-tight text-slate-900 mb-2">
          System Settings
        </h1>
        <p className="text-slate-500 max-w-2xl">
          Configure global customer mappings, AWS account integration, and
          define resource threshold overrides.
        </p>
      </div>

      <ErrorPanel message={error.message} onRetry={reset} />
    </div>
  );
}
