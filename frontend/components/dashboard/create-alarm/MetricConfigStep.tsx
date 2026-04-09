"use client";

import { useState } from "react";
import type { Track } from "@/lib/alarm-modal-utils";
import {
  MetricConfigSection,
  AVAILABLE_CW_METRICS,
  type MetricRow,
} from "@/components/resources/MetricConfigSection";

const UNIT_OPTIONS = ["Percent", "Count", "Bytes", "Seconds", "Milliseconds", "Gigabytes", "None"] as const;
const COMPARISON_OPTIONS = [
  { value: ">", label: "> Greater Than" },
  { value: ">=", label: ">= Greater Than or Equal" },
  { value: "<", label: "< Less Than" },
  { value: "<=", label: "<= Less Than or Equal" },
] as const;

interface MetricConfigStepProps {
  track: Track;
  resourceType: string;
  metrics: MetricRow[];
  setMetrics: React.Dispatch<React.SetStateAction<MetricRow[]>>;
  customMetrics: MetricRow[];
  setCustomMetrics: React.Dispatch<React.SetStateAction<MetricRow[]>>;
  showCustom: boolean;
  setShowCustom: (v: boolean) => void;
  selectedCwMetric: string;
  setSelectedCwMetric: (v: string) => void;
  customThreshold: number;
  setCustomThreshold: (v: number) => void;
  customUnit: string;
  setCustomUnit: (v: string) => void;
}

export function MetricConfigStep({
  track, resourceType,
  metrics, setMetrics, customMetrics, setCustomMetrics,
  showCustom, setShowCustom, selectedCwMetric, setSelectedCwMetric,
  customThreshold, setCustomThreshold, customUnit, setCustomUnit,
}: MetricConfigStepProps) {
  const cwMetrics = AVAILABLE_CW_METRICS[resourceType] ?? [];
  const availableCwMetrics = cwMetrics.filter(
    (m) => !customMetrics.some((c) => c.name === m.name)
  );
  const [customDirection, setCustomDirection] = useState(">");

  const addCustomFromDropdown = () => {
    if (!selectedCwMetric) return;
    const found = cwMetrics.find((m) => m.name === selectedCwMetric);
    if (!found) return;
    setCustomMetrics((prev) => [
      ...prev,
      {
        key: found.name,
        name: found.name,
        threshold: customThreshold,
        unit: customUnit || "Count",
        direction: customDirection,
        enabled: true,
      },
    ]);
    setSelectedCwMetric("");
    setCustomThreshold(0);
    setCustomUnit("");
    setCustomDirection(">");
    setShowCustom(false);
  };

  if (track === 1) {
    return (
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-slate-700">커스텀 메트릭 설정</h3>
        {cwMetrics.length === 0 ? (
          <p className="text-xs text-slate-400">
            이 리소스 타입에 사용 가능한 추가 CloudWatch 메트릭이 없습니다
          </p>
        ) : (
          <>
            <div>
              <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                CloudWatch 메트릭 선택
              </label>
              <select
                value={selectedCwMetric}
                onChange={(e) => setSelectedCwMetric(e.target.value)}
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none"
              >
                <option value="">메트릭을 선택하세요...</option>
                {availableCwMetrics.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} ({m.namespace})
                  </option>
                ))}
              </select>
            </div>
            {selectedCwMetric && (
              <div className="flex items-end gap-2">
                <div className="w-24">
                  <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">임계치</label>
                  <input type="number" value={customThreshold} onChange={(e) => setCustomThreshold(Number(e.target.value))} className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm font-mono" />
                </div>
                <div className="w-28">
                  <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">단위</label>
                  <select value={customUnit || "Count"} onChange={(e) => setCustomUnit(e.target.value)} className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm">
                    {UNIT_OPTIONS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </div>
                <div className="w-44">
                  <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">비교 연산자</label>
                  <select value={customDirection} onChange={(e) => setCustomDirection(e.target.value)} className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm">
                    {COMPARISON_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <button onClick={addCustomFromDropdown} className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white">추가</button>
              </div>
            )}
            {customMetrics.length > 0 && (
              <div className="rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <tbody>
                    {customMetrics.map((m, idx) => (
                      <tr key={idx} className="border-b border-slate-100 last:border-0">
                        <td className="px-3 py-2 font-medium">{m.name}</td>
                        <td className="px-3 py-2 text-xs text-slate-500">{m.direction} {m.threshold} {m.unit}</td>
                        <td className="px-3 py-2">
                          <button onClick={() => setCustomMetrics((prev) => prev.filter((_, j) => j !== idx))} className="text-red-400 hover:text-red-600 text-xs">삭제</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  // Track 2: reuse MetricConfigSection
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-700">메트릭 설정</h3>
      <MetricConfigSection
        selectedType={resourceType}
        metrics={metrics}
        setMetrics={setMetrics}
        customMetrics={customMetrics}
        setCustomMetrics={setCustomMetrics}
        showCustom={showCustom}
        setShowCustom={setShowCustom}
        selectedCwMetric={selectedCwMetric}
        setSelectedCwMetric={setSelectedCwMetric}
        customThreshold={customThreshold}
        setCustomThreshold={setCustomThreshold}
        customUnit={customUnit}
        setCustomUnit={setCustomUnit}
        availableCwMetrics={availableCwMetrics}
        addCustomFromDropdown={addCustomFromDropdown}
      />
    </div>
  );
}
