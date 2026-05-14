import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { ToastProvider } from "@/components/shared/Toast";
import { fetchAlarms } from "@/lib/server/data";
import type { Alarm } from "@/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Alarm Manager",
  description: "AWS CloudWatch Alarm Management Platform",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let alarms: Alarm[] = [];
  try {
    alarms = await fetchAlarms();
  } catch (error) {
    console.error("[RootLayout] Failed to fetch alarms:", error);
    // Fallback to empty array to allow the app shell to render
    alarms = [];
  }

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
