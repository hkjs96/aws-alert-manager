import { MOCK_ALARMS, MOCK_ALARM_SUMMARY, paginate } from "@/lib/mock-data";
import { AlarmsContent } from "@/components/alarms/AlarmsContent";
import type { AlarmStateFilter } from "@/types/api";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alarms | Alarm Manager",
  description: "Comprehensive list of all triggered and monitored alarm states.",
};

// When real backend API is ready, replace mock imports with:
// import { fetchAlarms, fetchAlarmSummary } from "@/lib/api-functions";

const VALID_STATES: AlarmStateFilter[] = ["ALL", "ALARM", "INSUFFICIENT", "OK", "OFF"];

interface AlarmsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function AlarmsPage({ searchParams }: AlarmsPageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const pageSize = [25, 50, 100].includes(Number(params.page_size))
    ? Number(params.page_size)
    : 25;
  const stateParam = String(params.state ?? "ALL").toUpperCase();
  const state: AlarmStateFilter = VALID_STATES.includes(stateParam as AlarmStateFilter)
    ? (stateParam as AlarmStateFilter)
    : "ALL";
  const search = typeof params.search === "string" ? params.search : "";

  // Pragmatic approach: use mock data directly for now.
  // When the real backend API is ready, swap to:
  //   const [alarmsRes, summary] = await Promise.all([
  //     fetchAlarms({ page, page_size: pageSize, state, search }),
  //     fetchAlarmSummary({}),
  //   ]);
  const filtered = MOCK_ALARMS.filter((a) => {
    const matchState = state === "ALL" || a.state === state;
    const matchSearch =
      !search ||
      a.resource.toLowerCase().includes(search.toLowerCase()) ||
      a.metric.toLowerCase().includes(search.toLowerCase());
    return matchState && matchSearch;
  });
  const result = paginate(filtered, page, pageSize);
  const summary = MOCK_ALARM_SUMMARY;

  return (
    <AlarmsContent
      alarms={result.items}
      summary={summary}
      total={result.total}
      page={result.page}
      pageSize={result.page_size}
      currentFilter={state}
      currentSearch={search}
    />
  );
}
