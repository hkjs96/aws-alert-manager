'use client';

import { AlertCircle, RefreshCw } from 'lucide-react';

interface ErrorPanelProps {
  message: string;
  onRetry: () => void;
}

export function ErrorPanel({ message, onRetry }: ErrorPanelProps) {
  return (
    <div
      data-testid="error-panel"
      className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3"
    >
      <AlertCircle className="h-5 w-5 shrink-0 text-red-600" />
      <p className="flex-1 text-sm text-red-800">{message}</p>
      <button
        data-testid="retry-button"
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 transition-colors"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        다시 시도
      </button>
    </div>
  );
}
