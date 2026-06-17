"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search, Bell, HelpCircle, Menu, AlertTriangle, CheckCircle2, LogOut } from "lucide-react";
import { signOut } from "next-auth/react";
import type { Alarm } from "@/types";
import { encodeResourceId } from "@/lib/resource-id";
import { GlobalFilterBar } from "./GlobalFilterBar";

interface TopBarProps {
  alarmCount?: number;
  onMenuToggle?: () => void;
  userEmail?: string | null;
  alarms?: Alarm[];
}

export function TopBar({ alarmCount = 0, onMenuToggle, userEmail = null, alarms = [] }: TopBarProps) {
  const hasAlarms = alarmCount > 0;
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [bellOpen, setBellOpen] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);

  // 벨 드롭다운 바깥 클릭 시 닫기
  useEffect(() => {
    if (!bellOpen) return;
    const onClick = (e: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) {
        setBellOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [bellOpen]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/resources?search=${encodeURIComponent(q)}` : "/resources");
  };

  const alarming = alarms.filter((a) => a.state === "ALARM");

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
          <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
            hasAlarms
              ? "bg-red-50 text-red-700 border-red-200"
              : "bg-green-50 text-green-700 border-green-200"
          }`}>
            {hasAlarms ? (
              <>
                <AlertTriangle size={11} />
                <span>ALARM {alarmCount}</span>
              </>
            ) : (
              <>
                <CheckCircle2 size={11} />
                <span>All clear</span>
              </>
            )}
          </div>
        </div>
        <GlobalFilterBar />
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

        {/* 알림 벨 + 드롭다운 */}
        <div className="relative" ref={bellRef}>
          <button
            onClick={() => setBellOpen((v) => !v)}
            className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors relative"
            aria-label="알림"
          >
            <Bell size={20} />
            {hasAlarms && (
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center border-2 border-white">
                {alarmCount > 9 ? "9+" : alarmCount}
              </span>
            )}
          </button>
          {bellOpen && (
            <div className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg z-50">
              <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-800">알림</span>
                <span className="text-[11px] font-semibold text-red-600">{alarming.length} ALARM</span>
              </div>
              {alarming.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-slate-400">현재 ALARM 상태인 알람이 없습니다</div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {alarming.slice(0, 20).map((a, i) => (
                    <li key={`${a.resource}-${a.metric}-${i}`}>
                      <Link
                        href={`/resources/${encodeResourceId(a.resource)}`}
                        onClick={() => setBellOpen(false)}
                        className="block px-4 py-2.5 hover:bg-slate-50 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <AlertTriangle size={13} className="text-red-500 shrink-0" />
                          <span className="text-sm font-semibold text-slate-800 truncate">{a.resource}</span>
                        </div>
                        <div className="ml-5 text-xs text-slate-500 truncate">{a.metric} · {a.type}</div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

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
