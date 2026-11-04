import { AlertEventsContent } from "@/components/alerts/AlertEventsContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Alert History | Alarm Manager",
  description: "Shows whether an alert was sent for each alarm, and if not, why.",
};

export default function AlertsPage() {
  return <AlertEventsContent />;
}
