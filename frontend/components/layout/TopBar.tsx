"use client";

import { Search, Bell, HelpCircle } from "lucide-react";
import { GlobalFilterBar } from "./GlobalFilterBar";

export function TopBar() {
  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-white/80 backdrop-blur-md border-b border-slate-200 flex items-center justify-between px-6 z-50">
      <div className="flex items-center gap-8">
        <span className="text-xl font-bold tracking-tighter text-slate-900 font-headline">Alarm Manager</span>
        <GlobalFilterBar />
      </div>
      <div className="flex items-center gap-4">
        <div className="relative hidden sm:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input type="text" placeholder="Search resources..."
            className="pl-10 pr-4 py-1.5 bg-slate-100 border-none rounded-full text-xs w-64 focus:ring-2 focus:ring-primary/20 outline-none" />
        </div>
        <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors"><Bell size={20} /></button>
        <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors"><HelpCircle size={20} /></button>
        <div className="h-8 w-8 rounded-full bg-slate-300 border border-slate-300" />
      </div>
    </header>
  );
}
