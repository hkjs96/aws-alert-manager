"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Bell, CheckCircle2 } from "lucide-react";
import type { AlarmBrief } from "@/lib/alarm-status";
import { encodeResourceId } from "@/lib/resource-id";

// --- 상태 배지 (TopBar 좌측, 제목 옆) ---

export function AlarmBadgeView({ count }: { count: number }) {
  const hasAlarms = count > 0;
  return (
    <div
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
        hasAlarms
          ? "bg-red-50 text-red-700 border-red-200"
          : "bg-green-50 text-green-700 border-green-200"
      }`}
    >
      {hasAlarms ? (
        <>
          <AlertTriangle size={11} />
          <span>ALARM {count}</span>
        </>
      ) : (
        <>
          <CheckCircle2 size={11} />
          <span>All clear</span>
        </>
      )}
    </div>
  );
}

/** 알람 데이터 도착 전 자리 표시 — 레이아웃 시프트 없이 중립 상태로 */
export function AlarmBadgeFallback() {
  return (
    <div
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border bg-slate-50 text-slate-400 border-slate-200"
      aria-busy="true"
    >
      <span>…</span>
    </div>
  );
}

// --- 알림 벨 (TopBar 우측) ---

interface AlarmBellViewProps {
  count: number;
  alarming: AlarmBrief[];
}

export function AlarmBellView({ count, alarming }: AlarmBellViewProps) {
  const hasAlarms = count > 0;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 드롭다운 바깥 클릭 시 닫기
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="p-2 text-slate-500 hover:bg-slate-100 rounded-full transition-colors relative"
        aria-label="알림"
      >
        <Bell size={20} />
        {hasAlarms && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center border-2 border-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg z-50">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <span className="text-sm font-semibold text-slate-800">알림</span>
            <span className="text-[11px] font-semibold text-red-600">{count} ALARM</span>
          </div>
          {alarming.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">현재 ALARM 상태인 알람이 없습니다</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {alarming.map((a, i) => (
                <li key={`${a.resource}-${a.metric}-${i}`}>
                  <Link
                    href={`/resources/${encodeResourceId(a.resource)}`}
                    onClick={() => setOpen(false)}
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
  );
}

export function AlarmBellFallback() {
  return (
    <div className="p-2 text-slate-300" aria-label="알림 불러오는 중" aria-busy="true">
      <Bell size={20} />
    </div>
  );
}

/** 필터 옵션 도착 전 자리 표시 — 실제 GlobalFilterBar와 같은 드롭다운 3개를 비활성으로 그려 레이아웃 시프트를 막는다 */
const FILTER_SELECT_CLASS =
  "rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-400 outline-none";

export function GlobalFilterBarFallback() {
  return (
    <div className="flex items-center gap-3" aria-busy="true" aria-hidden="true">
      {["All Customers", "All Accounts", "All Services"].map((label) => (
        <select key={label} disabled className={FILTER_SELECT_CLASS} defaultValue="">
          <option value="">{label}</option>
        </select>
      ))}
    </div>
  );
}
