"use client";

import { useEffect, useMemo, useState } from "react";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import type { Alarm } from "@/types";

const SIDEBAR_KEY = "alarm-mgr:sidebar-open";

interface AppShellProps {
  children: React.ReactNode;
  alarms?: Alarm[];
}

export function AppShell({ children, alarms = [] }: AppShellProps) {
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

  return (
    <div className="min-h-screen bg-surface">
      <TopBar
        alarmCount={alarmCount}
        onMenuToggle={toggle}
      />
      <Sidebar isOpen={sidebarOpen} onClose={close} />
      <main className="pt-16 min-h-screen">
        <div className="p-8 max-w-7xl mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
