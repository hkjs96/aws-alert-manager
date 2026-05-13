import { fetchAlarms, fetchAlarmSummary, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { AlarmsContent } from "@/components/alarms/AlarmsContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alarms | Alarm Manager",
  description: "Comprehensive list of all triggered and monitored alarm states.",
};

export default async function AlarmsPage() {
  let alarms = [], summary, customers = [], accounts = [];
  try {
    [alarms, summary, customers, accounts] = await Promise.all([
      fetchAlarms(),
      fetchAlarmSummary(),
      fetchCustomerOptions(),
      fetchAccountOptions(),
    ]);
  } catch (error) {
    console.error("[AlarmsPage] Failed to fetch data:", error);
    summary = { total: 0, alarm: 0, ok: 0, insufficient: 0, muted: 0 };
  }

  return (
    <AlarmsContent
      alarms={alarms}
      summary={summary}
      customers={customers}
      accounts={accounts}
    />
  );
}
