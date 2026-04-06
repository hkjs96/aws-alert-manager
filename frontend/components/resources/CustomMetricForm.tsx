"use client";

import { useState } from "react";
import type { DirectionSimple } from "@/types";

interface CustomMetricFormProps {
  onAdd: (metric: { name: string; threshold: number; direction: DirectionSimple; unit: string }) => void;
  onCancel: () => void;
  availableMetrics?: { metric_name: string; namespace: string }[];
}

export function CustomMetricForm({ onAdd, onCancel, availableMetrics = [] }: CustomMetricFormProps) {
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState<number>(0);
  const [direction, setDirection] = useState<DirectionSimple>(">");
  const [unit, setUnit] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);

  const filtered = availableMetrics.filter((m) =>
    m.metric_name.toLowerCase().includes(name.toLowerCase())
  );
  const found = availableMetrics.some((m) => m.metric_name === name);

  const handleSubmit = () => {
    if (!name || threshold <= 0) return;
    onAdd({ name, threshold, direction, unit });
  };

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative flex-1">
          <label className="mb-1 block text-xs font-medium text-slate-600">메트릭명</label>
          <input
            type="text"
            value={name}
            onChange={(e) => { setName(e.target.value); setShowSuggestions(true); }}
            onFocus={() => setShowSuggestions(true)}
            placeholder="메트릭명 입력 또는 선택..."
            className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm"
          />
          {showSuggestions && name && filtered.length > 0 && (
            <div className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-md border border-slate-200 bg-white shadow-lg">
              {filtered.slice(0, 10).map((m) => (
                <button
                  key={`${m.metric_name}-${m.namespace}`}
                  onClick={() => { setName(m.metric_name); setShowSuggestions(false); }}
                  className="block w-full px-3 py-1.5 text-left text-sm hover:bg-blue-50"
                >
                  {m.metric_name} <span className="text-xs text-slate-400">({m.namespace})</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">임계치</label>
          <input
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-24 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-mono"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">방향</label>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as DirectionSimple)}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm"
          >
            <option value=">">▲ Greater Than</option>
            <option value="<">▼ Less Than</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">단위</label>
          <input
            type="text"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="%"
            className="w-16 rounded-md border border-slate-200 px-3 py-1.5 text-sm"
          />
        </div>
        <button onClick={handleSubmit} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
          추가
        </button>
        <button onClick={onCancel} className="rounded-md border border-slate-200 px-3 py-1.5 text-sm hover:bg-slate-50">
          취소
        </button>
      </div>
      {name && (
        <div className="mt-2 text-xs">
          {found ? (
            <span className="text-green-600">✅ Metric found in CloudWatch</span>
          ) : (
            <span className="text-amber-600">⚠️ Metric not found. Alarm will be INSUFFICIENT_DATA until data appears.</span>
          )}
        </div>
      )}
    </div>
  );
}
