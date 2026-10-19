"use client";

import { useState, useCallback } from "react";
import { useToast } from "@/components/shared/Toast";
import { fetchAlarmOverlaps, toggleMonitoring, type AlarmOverlap } from "@/lib/api-functions";

interface UseMonitoringToggleReturn {
  loadingIds: Set<string>;
  toggle: (resourceId: string, currentState: boolean) => Promise<boolean>;
}

/**
 * 모니터링 토글 커스텀 훅
 * - 낙관적 업데이트 + 실패 시 롤백
 * - 리소스별 로딩 상태 관리
 * - 실패 시 에러 토스트
 * - 켤 때: 고객이 이미 같은 지표에 건 알람이 있으면 확인을 받는다(알림이 두 번 갈 수 있다). 막지는 않는다 —
 *   취소하면 아무것도 바꾸지 않는다. 점검 자체가 실패하면 안내일 뿐이므로 그대로 켠다.
 */

/** 확인창 문구 — 겹치는 지표와 고객 알람 이름, 빼는 방법. */
export function overlapMessage(resourceId: string, overlaps: AlarmOverlap[]): string {
  const lines = overlaps.map(
    (o) => `• ${o.metric}: ${o.customer_alarms.map((a) => a.name).join(", ")}`,
  );
  return [
    `${resourceId}에는 고객이 이미 만든 알람이 같은 지표를 보고 있습니다.`,
    "켜면 같은 장애에 알림이 두 번 갈 수 있습니다.",
    "",
    ...lines,
    "",
    "그래도 켤까요? (나중에 특정 지표만 빼려면 리소스에 Threshold_<지표>=off 태그)",
  ].join("\n");
}

async function confirmOverlaps(resourceId: string): Promise<boolean> {
  try {
    const { overlaps } = await fetchAlarmOverlaps(resourceId);
    return overlaps.length === 0 || window.confirm(overlapMessage(resourceId, overlaps));
  } catch {
    return true;
  }
}
export function useMonitoringToggle(): UseMonitoringToggleReturn {
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const { showToast } = useToast();

  const toggle = useCallback(
    async (resourceId: string, currentState: boolean): Promise<boolean> => {
      setLoadingIds((prev) => new Set(prev).add(resourceId));
      try {
        if (!currentState && !(await confirmOverlaps(resourceId))) {
          return false;
        }
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
