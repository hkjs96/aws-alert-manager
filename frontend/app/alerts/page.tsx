import { AlertEventsContent } from "@/components/alerts/AlertEventsContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alert History | Alarm Manager",
  description: "알람마다 알림을 보냈는지, 보내지 않았다면 왜인지 보여줍니다.",
};

export default function AlertsPage() {
  return <AlertEventsContent />;
}
