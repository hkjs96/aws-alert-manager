"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Layers, Bell, Users, Settings, HelpCircle, Info } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/resources", label: "Resources", icon: Layers },
  { href: "/alarms", label: "Alarms", icon: Bell },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
];

const BOTTOM_ITEMS = [
  { href: "#", label: "Support", icon: HelpCircle },
  { href: "#", label: "Docs", icon: Info },
];

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      {/* 오버레이 (모바일용 / 사이드바 열릴 때 배경 dimming) */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[1px] lg:hidden"
          onClick={onClose}
        />
      )}

      {/* 사이드바 본체 */}
      <aside
        className={`fixed left-0 top-0 h-full w-52 bg-white border-r border-slate-200 flex flex-col pt-16 pb-6 px-3 z-40
          transition-transform duration-300 ease-in-out
          ${isOpen ? "translate-x-0 shadow-xl shadow-slate-200/60" : "-translate-x-full"}`}
      >
        {/* Brand */}
        <div className="mb-6 px-2 pt-4">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-primary rounded-md flex items-center justify-center text-white shadow-sm flex-shrink-0">
              <Bell size={13} fill="currentColor" />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-800 leading-tight">Alarm Manager</p>
              <p className="text-[10px] text-slate-400 font-medium">AWS Monitoring</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 relative
                  ${active
                    ? "bg-primary/8 text-primary border-l-[3px] border-primary pl-[9px]"
                    : "text-slate-500 hover:text-slate-800 hover:bg-slate-100 border-l-[3px] border-transparent pl-[9px]"
                  }`}
              >
                <item.icon size={17} className="flex-shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Bottom */}
        <div className="space-y-0.5 pt-4 border-t border-slate-100">
          {BOTTOM_ITEMS.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="flex items-center gap-3 px-3 py-2 text-slate-400 hover:text-slate-700 text-xs font-medium transition-colors rounded-lg hover:bg-slate-100"
            >
              <item.icon size={15} className="flex-shrink-0" />
              <span>{item.label}</span>
            </Link>
          ))}
        </div>
      </aside>
    </>
  );
}
