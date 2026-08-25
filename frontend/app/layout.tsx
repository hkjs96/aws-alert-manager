import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Manrope } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { ToastProvider } from "@/components/shared/Toast";
import { fetchAlarms } from "@/lib/server/data";
import type { Alarm } from "@/types";
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
  let alarms: Alarm[] = [];
  try {
    alarms = await fetchAlarms();
  } catch (error) {
    console.error("[RootLayout] Failed to fetch alarms:", error);
    // Fallback to empty array to allow the app shell to render
    alarms = [];
  }

  // Only resolve a session when auth is configured (auth() requires AUTH_SECRET).
  const session = process.env.AUTH_SECRET ? await getSession() : null;

  return (
    <html
      lang="ko"
      className={`${inter.variable} ${manrope.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <ToastProvider>
          <AppShell alarms={alarms} userEmail={session?.user?.email ?? null}>
            {children}
          </AppShell>
        </ToastProvider>
      </body>
    </html>
  );
}
