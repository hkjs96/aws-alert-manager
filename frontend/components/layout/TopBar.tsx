"use client";

import { Search, Bell, HelpCircle, Menu } from "lucide-react";
import { GlobalFilterBar } from "./GlobalFilterBar";

interface TopBarProps {
  alarmCount?: number;
  onMenuToggle?: () => void;
}

export function TopBar({ alarmCount = 0, onMenuToggle }: TopBarProps) {
  const hasAlarms = alarmCount > 0;

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-white/80 backdrop-blur-md border-b border-slate-200 flex items-center justify-between px-4 z-50">
      <div className="flex items-center gap-3">
        {/* 햄버거 메뉴 버튼 */}
        <button
          onClick={onMenuToggle}
          className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
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
                <span>🔴</span>
                <span>ALARM {alarmCount}건</span>
              </>
            ) : (
              <>
                <span>✅</span>
                <span>정상</span>
              </>
            )}
          </div>
        </div>
        <GlobalFilterBar />
      </div>

      <div className="flex items-center gap-4">
        <div className="relative hidden sm:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input type="text" placeholder="Search resources..."
            className="pl-10 pr-4 py-1.5 bg-slate-100 border-none rounded-full text-xs w-64 focus:ring-2 focus:ring-primary/20 outline-none" />
        </div>
        <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors relative">
          <Bell size={20} />
          {hasAlarms && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center border-2 border-white">
              {alarmCount > 9 ? "9+" : alarmCount}
            </span>
          )}
        </button>
        <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors"><HelpCircle size={20} /></button>
        <div className="h-8 w-8 rounded-full bg-slate-300 border border-slate-300" />
      </div>
    </header>
  );
}
