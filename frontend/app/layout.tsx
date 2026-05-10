import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { ToastProvider } from "@/components/shared/Toast";
import { fetchAlarms } from "@/lib/server/data";

export const metadata: Metadata = {
  title: "Alarm Manager",
  description: "AWS CloudWatch Alarm Management Platform",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const alarms = await fetchAlarms();

  return (
    <html lang="ko">
      <body>
        <ToastProvider>
          <AppShell alarms={alarms}>{children}</AppShell>
        </ToastProvider>
      </body>
    </html>
  );
}
