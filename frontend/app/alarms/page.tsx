import { fetchAlarms, fetchAlarmSummary, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { AlarmsContent } from "@/components/alarms/AlarmsContent";
import type { Metadata } from "next";
import type { Alarm } from "@/types";
import type { AlarmSummary } from "@/types/api";

export const metadata: Metadata = {
  title: "Alarms | Alarm Manager",
  description: "Comprehensive list of all triggered and monitored alarm states.",
};

export default async function AlarmsPage() {
  let alarms: Alarm[] = [];
  let summary: AlarmSummary = { total: 0, alarm_count: 0, ok_count: 0, insufficient_count: 0 };
  let customers: { id: string; name: string }[] = [];
  let accounts: { id: string; name: string; customerId: string }[] = [];
  try {
    [alarms, summary, customers, accounts] = await Promise.all([
      fetchAlarms(),
      fetchAlarmSummary(),
      fetchCustomerOptions(),
      fetchAccountOptions(),
    ]);
  } catch (error) {
    console.error("[AlarmsPage] Failed to fetch data:", error);
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
