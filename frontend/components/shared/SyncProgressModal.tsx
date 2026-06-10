"use client";

import { useState, useEffect, useRef } from "react";
import { X, Loader2, CheckCircle2, AlertCircle, Info } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { fetchJobStatus } from "@/lib/api-functions";
import type { JobStatus, JobStatusValue, SyncTarget } from "@/types/api";

interface SyncProgressModalProps {
  isOpen: boolean;
  jobId: string;
  onClose: () => void;
  onSuccess: () => void;
  /** 동기화 대상: alarms | resources. 제목/통계 라벨만 분기. */
  target?: SyncTarget;
}

const TITLE: Record<SyncTarget, string> = {
  alarms: "Syncing AWS Alarms...",
  resources: "Syncing Resources...",
};

const PROGRESS_HINT: Record<SyncTarget, string> = {
  alarms: "Fetching current describe_alarms metrics from CloudWatch...",
  resources: "Discovering resources from AWS...",
};

export function SyncProgressModal({
  isOpen,
  jobId,
  onClose,
  onSuccess,
  target = "alarms",
}: SyncProgressModalProps) {
  const [status, setStatus] = useState<JobStatusValue>("pending");
  const [jobData, setJobData] = useState<JobStatus | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  // onSuccess를 ref로 보관해 폴링 effect 의존성에서 제외한다. 부모가 매 렌더마다
  // 인라인 onSuccess(=router.refresh)를 새로 만들기 때문에, 의존성에 두면 완료 →
  // onSuccess → 부모 리렌더 → effect 재구독 → status 리셋 → 재폴링 → 다시 완료
  // 로 이어지는 무한 루프가 발생한다. (AP-21)
  const onSuccessRef = useRef(onSuccess);
  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    if (!isOpen || !jobId) return;

    setStatus("pending");
    setErrorMsg("");
    setJobData(null);

    const poll = async () => {
      try {
        const data = await fetchJobStatus(jobId);
        setJobData(data);
        setStatus(data.status);

        if (
          data.status === "completed" ||
          data.status === "failed" ||
          data.status === "partial_failure"
        ) {
          clearInterval(intervalId);
          if (data.status === "completed") {
            onSuccessRef.current();
          }
        }
      } catch (err: unknown) {
        console.error("Failed to fetch job status:", err);
        setErrorMsg("Failed to connect to monitoring job tracker.");
        setStatus("failed");
        clearInterval(intervalId);
      }
    };

    // Schedule polling first so the interval id is available to poll()'s
    // self-clear before the immediate first fetch runs.
    const intervalId = setInterval(poll, 3000);
    poll();

    return () => clearInterval(intervalId);
  }, [isOpen, jobId]);

  if (!isOpen) return null;

  const isFinished = status === "completed" || status === "failed" || status === "partial_failure";

  // Aggregate stats — target에 따라 표시 항목이 다르다.
  const stats: { label: string; value: number }[] = [];
  if (jobData && jobData.results) {
    if (target === "resources") {
      let discovered = 0;
      let synced = 0;
      let removed = 0;
      jobData.results.forEach((r) => {
        discovered += r.discovered ?? 0;
        synced += r.synced ?? 0;
        removed += r.removed ?? 0;
      });
      stats.push(
        { label: "Discovered", value: discovered },
        { label: "Synced", value: synced },
        { label: "Removed", value: removed },
      );
    } else {
      let imported = 0;
      let deleted = 0;
      jobData.results.forEach((r) => {
        imported += r.imported ?? 0;
        deleted += r.deleted ?? 0;
      });
      stats.push(
        { label: "Imported Alarm Snapshots", value: imported },
        { label: "Deleted Stale Alarms", value: deleted },
      );
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl transition-all border border-slate-100 flex flex-col">
        {/* Close Button (only active if finished or error) */}
        {isFinished && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        )}

        <div className="p-6 text-center space-y-6">
          {/* Header & Status Icon */}
          <div className="flex flex-col items-center space-y-3 pt-4">
            {status === "pending" || status === "in_progress" ? (
              <div className="relative flex items-center justify-center">
                <Loader2 className="h-12 w-12 text-indigo-600 animate-spin" />
                <span className="absolute text-[10px] font-bold text-indigo-600 animate-pulse">SYNC</span>
              </div>
            ) : status === "completed" ? (
              <CheckCircle2 className="h-12 w-12 text-emerald-500 animate-bounce" />
            ) : (
              <AlertCircle className="h-12 w-12 text-rose-500 animate-pulse" />
            )}

            <h3 className="text-lg font-bold text-slate-800">
              {status === "pending" && "Preparing Sync..."}
              {status === "in_progress" && TITLE[target]}
              {status === "completed" && "Sync Completed!"}
              {status === "partial_failure" && "Partial Sync Success"}
              {status === "failed" && "Sync Failed"}
            </h3>

            <p className="text-xs text-slate-400 font-mono">Job ID: {jobId}</p>
          </div>

          {/* Progress / Details Box */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-100 text-left space-y-3">
            <div className="flex justify-between items-center text-xs font-semibold text-slate-600">
              <span>Status</span>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold capitalize ${
                status === "completed" ? "bg-emerald-100 text-emerald-800" :
                status === "failed" ? "bg-rose-100 text-rose-800" :
                status === "in_progress" ? "bg-indigo-100 text-indigo-800 animate-pulse" :
                "bg-slate-100 text-slate-800"
              }`}>
                {status.replace("_", " ")}
              </span>
            </div>

            {/* Custom progress indicators */}
            {(status === "pending" || status === "in_progress") && (
              <div className="space-y-1">
                <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-indigo-600 h-1.5 rounded-full animate-pulse w-full" />
                </div>
                <p className="text-[10px] text-slate-400 text-center">{PROGRESS_HINT[target]}</p>
              </div>
            )}

            {isFinished && jobData && (
              <div className="space-y-2 pt-1 border-t border-slate-100 text-xs">
                {stats.map((s) => (
                  <div key={s.label} className="flex justify-between text-slate-500">
                    <span>{s.label}</span>
                    <span className="font-semibold text-slate-800">{s.value}</span>
                  </div>
                ))}
                {jobData.failed_count > 0 && (
                  <div className="flex justify-between text-rose-600 font-semibold">
                    <span>Failed Accounts</span>
                    <span>{jobData.failed_count}</span>
                  </div>
                )}
              </div>
            )}

            {errorMsg && (
              <div className="flex items-start gap-2 text-rose-600 text-xs mt-2 bg-rose-50 p-2.5 rounded-lg border border-rose-100">
                <Info size={14} className="shrink-0 mt-0.5" />
                <span>{errorMsg}</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex justify-end">
          <Button
            variant={isFinished ? "primary" : "secondary"}
            onClick={onClose}
            disabled={!isFinished}
            className="rounded-xl w-full"
          >
            {isFinished ? "Close" : "Syncing..."}
          </Button>
        </div>
      </div>
    </div>
  );
}
