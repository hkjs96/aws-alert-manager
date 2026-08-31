"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search, HelpCircle, Menu, LogOut } from "lucide-react";
import { signOut } from "next-auth/react";

interface TopBarProps {
  onMenuToggle?: () => void;
  userEmail?: string | null;
  /**
   * 서버 컴포넌트 슬롯 — 루트 레이아웃이 Suspense로 감싸 내려준다.
   * 알람/필터 데이터 fetch가 셸 렌더를 막지 않도록 TopBar는 자리만 제공한다.
   */
  alarmBadge?: ReactNode;
  alarmBell?: ReactNode;
  filterBar?: ReactNode;
}

export function TopBar({ onMenuToggle, userEmail = null, alarmBadge, alarmBell, filterBar }: TopBarProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/resources?search=${encodeURIComponent(q)}` : "/resources");
  };

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-white/80 backdrop-blur-md border-b border-slate-200 flex items-center justify-between px-4 z-50">
      <div className="flex items-center gap-3">
        {/* 햄버거 메뉴 버튼 */}
        <button
          onClick={onMenuToggle}
          className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors lg:hidden"
          aria-label="메뉴 열기/닫기"
        >
          <Menu size={20} />
        </button>
        <div className="flex items-center gap-3">
          <span className="text-base font-bold tracking-tight text-slate-900 font-headline">Alarm Manager</span>
          {alarmBadge}
        </div>
        {filterBar}
      </div>

      <div className="flex items-center gap-4">
        <form onSubmit={handleSearch} className="relative hidden sm:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search resources..."
            aria-label="리소스 검색"
            className="pl-10 pr-4 py-1.5 bg-slate-100 border-none rounded-full text-xs w-64 focus:ring-2 focus:ring-primary/20 outline-none"
          />
        </form>

        {/* 알림 벨 + 드롭다운 (서버 슬롯) */}
        {alarmBell}

        <Link
          href="/help"
          className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors"
          aria-label="도움말"
          title="도움말 / 사용 가이드"
        >
          <HelpCircle size={20} />
        </Link>

        {userEmail ? (
          <div className="flex items-center gap-2">
            <span className="hidden md:inline text-xs text-slate-600 max-w-[180px] truncate" title={userEmail}>
              {userEmail}
            </span>
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-full transition-colors"
              aria-label="로그아웃"
              title="로그아웃"
            >
              <LogOut size={18} />
            </button>
          </div>
        ) : (
          <div className="h-8 w-8 rounded-full bg-slate-300 border border-slate-300" />
        )}
      </div>
    </header>
  );
}
