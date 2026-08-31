import { fetchAlarms } from "@/lib/server/data";
import { summarizeAlarms, type AlarmStatusSummary } from "@/lib/alarm-status";
import { AlarmBellView } from "./AlarmStatusViews";

/** TopBar 알림 벨 (서버 컴포넌트, Suspense 슬롯). AlarmBadge와 같은 cache()된 fetch를 쓴다. */
export async function AlarmBell() {
  let summary: AlarmStatusSummary = { count: 0, alarming: [] };
  try {
    summary = summarizeAlarms(await fetchAlarms());
  } catch (error) {
    console.error("[AlarmBell] Failed to fetch alarms:", error);
  }
  return <AlarmBellView count={summary.count} alarming={summary.alarming} />;
}
