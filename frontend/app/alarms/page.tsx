import { getAlarms } from "@/lib/mock-store";
import { MOCK_ALARM_SUMMARY, MOCK_CUSTOMERS, MOCK_ACCOUNTS } from "@/lib/mock-data";
import { AlarmsContent } from "@/components/alarms/AlarmsContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alarms | Alarm Manager",
  description: "Comprehensive list of all triggered and monitored alarm states.",
};

export default async function AlarmsPage() {
  const alarms = getAlarms();
  const summary = MOCK_ALARM_SUMMARY;
  const customers = MOCK_CUSTOMERS.map((c) => ({ id: c.customer_id, name: c.name }));
  const accounts = MOCK_ACCOUNTS.map((a) => ({ id: a.account_id, name: a.name, customerId: a.customer_id }));

  return (
    <AlarmsContent
      alarms={alarms}
      summary={summary}
      customers={customers}
      accounts={accounts}
    />
  );
}
