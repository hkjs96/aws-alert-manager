"use client";

import { Eye, EyeOff, Settings, AlertTriangle } from "lucide-react";
import { Button } from "@/components/shared/Button";

interface BulkActionBarProps {
  selectedCount: number;
  isMixedType: boolean;
  onEnable: () => void;
  onDisable: () => void;
  /** 같은 타입일 때만 — 임계치·판단 방식 일괄 변경 */
  onConfigure: () => void;
}

export function BulkActionBar({
  selectedCount,
  isMixedType,
  onEnable,
  onDisable,
  onConfigure,
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
        <Button variant="secondary" size="sm" onClick={onEnable} icon={<Eye size={14} />}>
          Enable
        </Button>
        <Button variant="secondary" size="sm" onClick={onDisable} icon={<EyeOff size={14} />}>
          Disable
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={isMixedType}
          title={isMixedType ? "같은 타입 리소스만 함께 설정할 수 있습니다" : undefined}
          onClick={onConfigure}
          icon={<Settings size={14} />}
        >
          Configure Alarms
        </Button>
      </div>
    </div>
  );
}
