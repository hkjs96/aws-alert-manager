"use client";

import { Eye, EyeOff, Settings, AlertTriangle } from "lucide-react";

interface BulkActionBarProps {
  selectedCount: number;
  isMixedType: boolean;
  onEnable: () => void;
  onDisable: () => void;
}

export function BulkActionBar({
  selectedCount,
  isMixedType,
  onEnable,
  onDisable,
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="flex items-center gap-4 rounded-xl border border-blue-200 bg-blue-50 px-5 py-3 shadow-sm">
      <span className="rounded-lg bg-primary px-3 py-1.5 text-sm font-bold text-white">
        {selectedCount} SELECTED
      </span>
      <span className="text-sm text-slate-600">
        Resources targeted for bulk update
      </span>
      {isMixedType && selectedCount > 1 && (
        <span className="flex items-center gap-1 text-xs text-amber-600 font-medium">
          <AlertTriangle size={12} /> Mixed types — alarm config disabled
        </span>
      )}
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onEnable}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <Eye size={14} /> Enable
        </button>
        <button
          onClick={onDisable}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <EyeOff size={14} /> Disable
        </button>
        <button className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm">
          <Settings size={14} /> Configure Alarms
        </button>
      </div>
    </div>
  );
}
