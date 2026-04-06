"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Job } from "@/types";

export function useJobPolling(jobId: string | null, intervalMs = 2000) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const poll = useCallback(async () => {
    if (!jobId) return;
    try {
      const data = await api.get<Job>(`/jobs/${jobId}`);
      setJob(data);
      if (data.status === "completed" || data.status === "failed" || data.status === "partial_failure") {
        return true; // done
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "작업 상태 조회 실패");
      return true; // stop polling on error
    }
    return false;
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;
    let timer: ReturnType<typeof setInterval>;
    const start = async () => {
      const done = await poll();
      if (!done) {
        timer = setInterval(async () => {
          const finished = await poll();
          if (finished) clearInterval(timer);
        }, intervalMs);
      }
    };
    start();
    return () => clearInterval(timer);
  }, [jobId, intervalMs, poll]);

  return { job, error };
}
