"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import type { Alarm } from "@/types";

const SIDEBAR_KEY = "alarm-mgr:sidebar-open";

interface AppShellProps {
  children: React.ReactNode;
  alarms?: Alarm[];
  userEmail?: string | null;
}

export function AppShell({ children, alarms = [], userEmail = null }: AppShellProps) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 마운트 시 localStorage에서 상태 복원
  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_KEY);
    if (saved !== null) setSidebarOpen(saved === "true");
  }, []);

  // 변경될 때마다 localStorage에 저장
  const toggle = () =>
    setSidebarOpen((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_KEY, String(next));
      return next;
    });

  const close = () => {
    setSidebarOpen(false);
    localStorage.setItem(SIDEBAR_KEY, "false");
  };

  const alarmCount = useMemo(
    () => alarms.filter((a) => a.state === "ALARM").length,
    [alarms],
  );

  // 로그인/도움말 페이지는 셸(사이드바/탑바) 없이 단독 렌더한다.
  // (도움말은 로그인 전에도 접근 가능해야 하므로 셸에 의존하지 않음)
  if (pathname === "/login" || pathname === "/help") {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-surface">
      <TopBar
        alarmCount={alarmCount}
        onMenuToggle={toggle}
        userEmail={userEmail}
        alarms={alarms}
      />
      <Sidebar isOpen={sidebarOpen} onClose={close} />
      <main className="pt-16 min-h-screen lg:ml-52">
        <div className="p-8 max-w-7xl mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
