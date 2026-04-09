"use client";

import { Info } from "lucide-react";

interface InfoBannerProps {
  message: string;
}

export function InfoBanner({ message }: InfoBannerProps) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50/60 px-4 py-3">
      <Info size={16} className="mt-0.5 shrink-0 text-blue-500" />
      <p className="text-xs text-blue-700">{message}</p>
    </div>
  );
}
