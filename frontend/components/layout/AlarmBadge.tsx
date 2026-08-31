import { fetchAlarms } from "@/lib/server/data";
import { summarizeAlarms } from "@/lib/alarm-status";
import { AlarmBadgeView } from "./AlarmStatusViews";

/**
 * TopBar 상태 배지 (서버 컴포넌트).
 * 루트 레이아웃이 알람을 await하지 않도록 Suspense 슬롯으로 렌더한다 —
 * 셸은 즉시 스트리밍되고 배지는 데이터가 오면 채워진다.
 * fetchAlarms는 요청 단위 cache()라 같은 요청의 페이지 fetch와 합산 1회.
 */
export async function AlarmBadge() {
  let count = 0;
  try {
    count = summarizeAlarms(await fetchAlarms()).count;
  } catch (error) {
    console.error("[AlarmBadge] Failed to fetch alarms:", error);
  }
  return <AlarmBadgeView count={count} />;
}
