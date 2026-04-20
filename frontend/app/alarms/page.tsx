import { fetchAlarms, fetchAlarmSummary, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { AlarmsContent } from "@/components/alarms/AlarmsContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alarms | Alarm Manager",
  description: "Comprehensive list of all triggered and monitored alarm states.",
};

export default async function AlarmsPage() {
  const [alarms, summary, customers, accounts] = await Promise.all([
    fetchAlarms(),
    fetchAlarmSummary(),
    fetchCustomerOptions(),
    fetchAccountOptions(),
  ]);

  return (
    <AlarmsContent
      alarms={alarms}
      summary={summary}
      customers={customers}
      accounts={accounts}
    />
  );
}
