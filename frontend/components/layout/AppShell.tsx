"use client";

import { GlobalFilterProvider } from "@/hooks/useGlobalFilter";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { GlobalFilter } from "./GlobalFilter";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <GlobalFilterProvider>
      <TopBar customerFilter={<GlobalFilter />} />
      <Sidebar />
      <main className="ml-60 mt-14 min-h-[calc(100vh-3.5rem)] p-6">
        {children}
      </main>
    </GlobalFilterProvider>
  );
}
