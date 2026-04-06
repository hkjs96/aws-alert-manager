"use client";

interface BulkProgressBarProps {
  total: number;
  completed: number;
  failed: number;
  status: string;
}

export function BulkProgressBar({ total, completed, failed, status }: BulkProgressBarProps) {
  const progress = total > 0 ? ((completed + failed) / total) * 100 : 0;
  const isComplete = status === "completed" || status === "partial_failure" || status === "failed";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="text-slate-600">
          {isComplete ? "완료" : "처리 중..."} ({completed + failed}/{total})
        </span>
        {failed > 0 && (
          <span className="text-red-600">{failed}건 실패</span>
        )}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            failed > 0 ? "bg-amber-500" : "bg-accent"
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
