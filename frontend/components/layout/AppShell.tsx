"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";

const SIDEBAR_KEY = "alarm-mgr:sidebar-open";

interface AppShellProps {
  children: ReactNode;
  userEmail?: string | null;
  /** 루트 레이아웃이 Suspense로 감싼 서버 컴포넌트 슬롯 (TopBar로 전달) */
  alarmBadge?: ReactNode;
  alarmBell?: ReactNode;
  filterBar?: ReactNode;
}

export function AppShell({
  children, userEmail = null, alarmBadge, alarmBell, filterBar,
}: AppShellProps) {
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

  // 로그인/도움말 페이지는 셸(사이드바/탑바) 없이 단독 렌더한다.
  // (도움말은 로그인 전에도 접근 가능해야 하므로 셸에 의존하지 않음)
  if (pathname === "/login" || pathname === "/help") {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-surface">
      <TopBar
        onMenuToggle={toggle}
        userEmail={userEmail}
        alarmBadge={alarmBadge}
        alarmBell={alarmBell}
        filterBar={filterBar}
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
