"use client";

import { Bell, User } from "lucide-react";

interface TopBarProps {
  customerFilter: React.ReactNode;
}

export function TopBar({ customerFilter }: TopBarProps) {
  return (
    <header className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4">
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold text-accent">Alarm Manager</span>
      </div>

      <div className="flex items-center gap-3">
        {customerFilter}
      </div>

      <div className="flex items-center gap-3">
        <button className="relative rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
          <Bell size={20} />
          <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            3
          </span>
        </button>
        <button className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-sm font-medium text-white">
          <User size={16} />
        </button>
      </div>
    </header>
  );
}
