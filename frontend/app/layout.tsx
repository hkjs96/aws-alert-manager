import type { Metadata } from "next";
import { Suspense } from "react";
import { Inter, JetBrains_Mono, Manrope } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { AlarmBadge } from "@/components/layout/AlarmBadge";
import { AlarmBell } from "@/components/layout/AlarmBell";
import { GlobalFilterOptions } from "@/components/layout/GlobalFilterOptions";
import {
  AlarmBadgeFallback,
  AlarmBellFallback,
  GlobalFilterBarFallback,
} from "@/components/layout/AlarmStatusViews";
import { ToastProvider } from "@/components/shared/Toast";
import { WebVitals } from "@/components/shared/WebVitals";
import { getSession } from "@/lib/server/session";

// next/font self-hosts and preloads the faces. Loading them through an
// @import in globals.css blocks the first render on a Google Fonts round trip.
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const manrope = Manrope({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-manrope",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Alarm Manager",
  description: "AWS CloudWatch Alarm Management Platform",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Only resolve a session when auth is configured (auth() requires AUTH_SECRET).
  const session = process.env.AUTH_SECRET ? await getSession() : null;

  // 인증이 켜져 있는데 세션이 없으면 미들웨어가 /login으로 보내는 요청이다 — 셸이
  // 렌더되지 않으므로 슬롯 fetch(실패가 예정된 3콜)를 아예 만들지 않는다.
  const hasShellData = !process.env.AUTH_SECRET || session !== null;

  // 알람 배지·벨·필터 옵션은 셸의 첫 바이트를 막지 않도록 Suspense 슬롯으로 스트리밍한다.
  // (예전에는 레이아웃이 alarms를 await해 모든 하드 로드의 TTFB가 그 fetch에 묶였다)
  const alarmBadge = hasShellData ? (
    <Suspense fallback={<AlarmBadgeFallback />}>
      <AlarmBadge />
    </Suspense>
  ) : null;
  const alarmBell = hasShellData ? (
    <Suspense fallback={<AlarmBellFallback />}>
      <AlarmBell />
    </Suspense>
  ) : null;
  const filterBar = hasShellData ? (
    <Suspense fallback={<GlobalFilterBarFallback />}>
      <GlobalFilterOptions />
    </Suspense>
  ) : null;

  return (
    <html
      lang="ko"
      className={`${inter.variable} ${manrope.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <WebVitals />
        <ToastProvider>
          <AppShell
            userEmail={session?.user?.email ?? null}
            alarmBadge={alarmBadge}
            alarmBell={alarmBell}
            filterBar={filterBar}
          >
            {children}
          </AppShell>
        </ToastProvider>
      </body>
    </html>
  );
}
