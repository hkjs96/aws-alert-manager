"use client";

interface BulkActionBarProps {
  selectedCount: number;
  onClear: () => void;
  onEnableMonitoring: () => void;
  onDisableMonitoring: () => void;
  onConfigureAlarms: () => void;
}

export function BulkActionBar({
  selectedCount,
  onClear,
  onEnableMonitoring,
  onDisableMonitoring,
  onConfigureAlarms,
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-0 left-60 right-0 z-20 flex h-16 items-center justify-between border-t border-slate-200 bg-white px-6 shadow-[0_-2px_8px_rgba(0,0,0,0.06)]">
      <div className="flex items-center gap-3">
        <span className="rounded-md bg-accent px-2.5 py-1 text-sm font-medium text-white">
          {selectedCount}개 선택
        </span>
        <button onClick={onClear} className="text-sm text-slate-500 hover:text-slate-700 underline">
          해제
        </button>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onEnableMonitoring}
          className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
        >
          모니터링 활성화
        </button>
        <button
          onClick={onDisableMonitoring}
          className="rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50"
        >
          모니터링 비활성화
        </button>
        <button
          onClick={onConfigureAlarms}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          알람 설정
        </button>
        <button className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50">
          CSV 내보내기
        </button>
      </div>
    </div>
  );
}
