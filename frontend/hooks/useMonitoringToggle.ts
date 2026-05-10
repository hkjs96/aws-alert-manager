"use client";

import { useState, useCallback } from "react";
import { useToast } from "@/components/shared/Toast";
import { toggleMonitoring } from "@/lib/api-functions";

interface UseMonitoringToggleReturn {
  loadingIds: Set<string>;
  toggle: (resourceId: string, currentState: boolean) => Promise<boolean>;
}

/**
 * 모니터링 토글 커스텀 훅
 * - 낙관적 업데이트 + 실패 시 롤백
 * - 리소스별 로딩 상태 관리
 * - 실패 시 에러 토스트
 */
export function useMonitoringToggle(): UseMonitoringToggleReturn {
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const { showToast } = useToast();

  const toggle = useCallback(
    async (resourceId: string, currentState: boolean): Promise<boolean> => {
      setLoadingIds((prev) => new Set(prev).add(resourceId));
      try {
        await toggleMonitoring(resourceId, !currentState);
        return true;
      } catch {
        showToast("error", `모니터링 상태 변경에 실패했습니다 (${resourceId})`);
        return false;
      } finally {
        setLoadingIds((prev) => {
          const next = new Set(prev);
          next.delete(resourceId);
          return next;
        });
      }
    },
    [showToast],
  );

  return { loadingIds, toggle };
}
