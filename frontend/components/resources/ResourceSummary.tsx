"use client";

import { useMemo } from "react";

import type { Resource } from "@/types";

/** 지금 필터 기준 몇 개가 있는지 — 표만 봐서는 페이지 단위라 전체 규모를 알 수 없다. */
export function ResourceSummary({
  resources,
  typeFilter,
  onTypeChange,
}: {
  resources: Resource[];
  typeFilter: string;
  onTypeChange: (type: string) => void;
}) {
  const { monitored, alarming, byType } = useMemo(() => {
    const counts = new Map<string, number>();
    let on = 0;
    let firing = 0;
    for (const r of resources) {
      counts.set(r.type, (counts.get(r.type) ?? 0) + 1);
      if (r.monitoring) on += 1;
      if (r.alarms.critical + r.alarms.warning > 0) firing += 1;
    }
    return {
      monitored: on,
      alarming: firing,
      byType: [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    };
  }, [resources]);

  const stat = (label: string, value: number, tone = "text-slate-900") => (
    <div>
      <div className="text-[11px] font-semibold text-slate-500">{label}</div>
      <div className={`text-2xl font-extrabold ${tone}`}>{value.toLocaleString()}</div>
    </div>
  );

  return (
    <section
      aria-label="리소스 요약"
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap gap-8">
        {stat("리소스", resources.length)}
        {stat("모니터링 켬", monitored, "text-green-700")}
        {stat("모니터링 끔", resources.length - monitored, "text-slate-500")}
        {stat("알람 발생 중", alarming, alarming ? "text-red-600" : "text-slate-500")}
      </div>
      {byType.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {byType.map(([type, count]) => {
            const on = typeFilter === type;
            return (
              <button
                key={type}
                type="button"
                aria-pressed={on}
                onClick={() => onTypeChange(on ? "" : type)}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${
                  on
                    ? "border-primary bg-primary text-white"
                    : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-400"
                }`}
              >
                {type} <span className="font-semibold">{count}</span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
