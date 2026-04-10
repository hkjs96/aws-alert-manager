"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Layers, Bell, Users, Settings, HelpCircle, Info, Zap } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/resources", label: "Resources", icon: Layers },
  { href: "/alarms", label: "Alarms", icon: Bell },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
];

const BOTTOM_ITEMS = [
  { href: "#", label: "Support", icon: HelpCircle },
  { href: "#", label: "Documentation", icon: Info },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-full w-64 bg-slate-50 border-r border-slate-200 flex flex-col pt-20 pb-6 px-4 z-40">
      {/* Brand */}
      <div className="mb-8 px-2">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Zap size={20} fill="currentColor" />
          </div>
          <div>
            <h2 className="text-lg font-black text-slate-900 font-headline leading-tight">Precision Arch</h2>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Enterprise Tier</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link key={item.href} href={item.href}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 font-medium text-sm ${
                active
                  ? "bg-white text-primary shadow-sm ring-1 ring-slate-200"
                  : "text-slate-500 hover:text-slate-900 hover:bg-slate-200/50"
              }`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="mt-auto space-y-1 pt-4 border-t border-slate-200">
        {BOTTOM_ITEMS.map((item) => (
          <Link key={item.label} href={item.href}
            className="w-full flex items-center gap-3 px-3 py-2 text-slate-500 hover:text-slate-900 text-sm font-medium">
            <item.icon size={18} />
            <span>{item.label}</span>
          </Link>
        ))}
      </div>
    </aside>
  );
}
