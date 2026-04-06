"use client";

import { useState } from "react";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

interface MetricDefault {
  metric_key: string;
  metric_name: string;
  direction: ">" | "<";
  default_value: number;
  unit: string;
  overrides: { customer_id: string; customer_name: string; value: number }[];
}

// TODO: Load from API per resource type
const MOCK_EC2_METRICS: MetricDefault[] = [
  { metric_key: "CPU", metric_name: "CPUUtilization", direction: ">", default_value: 80, unit: "%", overrides: [{ customer_id: "acme", customer_name: "Acme Corp", value: 90 }] },
  { metric_key: "Memory", metric_name: "mem_used_percent", direction: ">", default_value: 80, unit: "%", overrides: [] },
  { metric_key: "Disk", metric_name: "disk_used_percent", direction: ">", default_value: 80, unit: "%", overrides: [] },
  { metric_key: "StatusCheckFailed", metric_name: "StatusCheckFailed", direction: ">", default_value: 0, unit: "", overrides: [] },
];

export function ThresholdOverrideTabs() {
  const [activeType, setActiveType] = useState(SUPPORTED_RESOURCE_TYPES[0]);
  const metrics = MOCK_EC2_METRICS; // TODO: switch by activeType

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="mb-4 text-sm font-medium text-slate-700">알람 임계치 오버라이드</h3>

      {/* Resource type tabs */}
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 pb-2">
        {SUPPORTED_RESOURCE_TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setActiveType(t)}
            className={`whitespace-nowrap rounded-md px-3 py-1 text-xs font-medium transition-colors ${
              activeType === t ? "bg-accent text-white" : "text-slate-500 hover:bg-slate-100"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-3 gap-3">
        {metrics.map((m) => (
          <div key={m.metric_key} className="rounded-lg border border-slate-200 p-4">
            <div className="mb-2 text-sm font-medium text-accent">{m.metric_key}</div>
            <div className="mb-1 text-xs text-slate-400">{m.metric_name}</div>
            <div className="mb-3 text-2xl font-bold text-slate-800">
              {m.direction} {m.default_value}<span className="text-sm font-normal text-slate-400"> {m.unit}</span>
            </div>
            <div className="text-xs text-slate-500">시스템 기본값</div>

            {m.overrides.length > 0 && (
              <div className="mt-3 border-t border-slate-100 pt-2">
                <div className="mb-1 text-xs font-medium uppercase text-slate-400">고객사 오버라이드</div>
                {m.overrides.map((o) => (
                  <div key={o.customer_id} className="flex items-center justify-between text-sm">
                    <span>{o.customer_name}</span>
                    <span className="font-mono text-accent">{m.direction} {o.value}</span>
                  </div>
                ))}
              </div>
            )}

            <button className="mt-2 text-xs text-accent hover:underline">+ 오버라이드 추가</button>
          </div>
        ))}
      </div>
    </div>
  );
}
