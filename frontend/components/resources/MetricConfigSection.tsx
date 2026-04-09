"use client";

import { Plus, Trash2 } from "lucide-react";

export type MetricRow = {
  key: string;
  name: string;
  threshold: number;
  unit: string;
  direction: string;
  enabled: boolean;
};

export const METRICS_BY_TYPE: Record<string, MetricRow[]> = {
  EC2: [
    { key: "CPU", name: "CPUUtilization", threshold: 80, unit: "%", direction: ">", enabled: true },
    { key: "Memory", name: "mem_used_percent", threshold: 80, unit: "%", direction: ">", enabled: true },
    { key: "Disk", name: "disk_used_percent", threshold: 80, unit: "%", direction: ">", enabled: true },
    { key: "StatusCheck", name: "StatusCheckFailed", threshold: 0, unit: "", direction: ">", enabled: true },
  ],
  RDS: [
    { key: "CPU", name: "CPUUtilization", threshold: 80, unit: "%", direction: ">", enabled: true },
    { key: "FreeMemory", name: "FreeableMemory", threshold: 2, unit: "GB", direction: "<", enabled: true },
    { key: "FreeStorage", name: "FreeStorageSpace", threshold: 10, unit: "GB", direction: "<", enabled: true },
    { key: "Connections", name: "DatabaseConnections", threshold: 100, unit: "Count", direction: ">", enabled: true },
  ],
  S3: [
    { key: "BucketSize", name: "BucketSizeBytes", threshold: 500, unit: "GB", direction: ">", enabled: true },
    { key: "Objects", name: "NumberOfObjects", threshold: 1000000, unit: "Count", direction: ">", enabled: true },
  ],
  LAMBDA: [
    { key: "Errors", name: "Errors", threshold: 5, unit: "Count", direction: ">", enabled: true },
    { key: "Duration", name: "Duration", threshold: 10000, unit: "ms", direction: ">", enabled: true },
    { key: "Throttles", name: "Throttles", threshold: 0, unit: "Count", direction: ">", enabled: true },
  ],
  NET: [
    { key: "5XX", name: "HTTPCode_ELB_5XX_Count", threshold: 50, unit: "Count", direction: ">", enabled: true },
    { key: "ResponseTime", name: "TargetResponseTime", threshold: 2, unit: "s", direction: ">", enabled: true },
    { key: "HealthyHosts", name: "HealthyHostCount", threshold: 2, unit: "Count", direction: "<", enabled: true },
  ],
};

export const AVAILABLE_CW_METRICS: Record<string, { name: string; namespace: string }[]> = {
  EC2: [
    { name: "NetworkIn", namespace: "AWS/EC2" },
    { name: "NetworkOut", namespace: "AWS/EC2" },
    { name: "DiskReadOps", namespace: "AWS/EC2" },
    { name: "custom_app_latency", namespace: "CustomApp" },
  ],
  RDS: [
    { name: "CommitLatency", namespace: "AWS/RDS" },
    { name: "ReadLatency", namespace: "AWS/RDS" },
    { name: "WriteLatency", namespace: "AWS/RDS" },
    { name: "ReplicaLag", namespace: "AWS/RDS" },
  ],
  LAMBDA: [
    { name: "ConcurrentExecutions", namespace: "AWS/Lambda" },
    { name: "IteratorAge", namespace: "AWS/Lambda" },
  ],
  S3: [],
  NET: [
    { name: "RequestCount", namespace: "AWS/ApplicationELB" },
    { name: "ProcessedBytes", namespace: "AWS/ApplicationELB" },
  ],
};

interface MetricConfigSectionProps {
  selectedType: string | null;
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
  availableCwMetrics: { name: string; namespace: string }[];
  addCustomFromDropdown: () => void;
}

export function MetricConfigSection({
  selectedType, metrics, setMetrics, customMetrics, setCustomMetrics,
  showCustom, setShowCustom, selectedCwMetric, setSelectedCwMetric,
  customThreshold, setCustomThreshold, customUnit, setCustomUnit,
  availableCwMetrics, addCustomFromDropdown,
}: MetricConfigSectionProps) {
  return (
    <>
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium text-slate-700">기본 메트릭</h4>
        <span className="text-[10px] bg-slate-100 px-2 py-0.5 rounded font-bold text-slate-500">{selectedType}</span>
      </div>
      <div className="rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <tr><th className="w-10 px-3 py-2" /><th className="px-3 py-2">메트릭</th><th className="px-3 py-2">CW 메트릭</th><th className="px-3 py-2 w-24">임계치</th><th className="px-3 py-2 w-14">단위</th><th className="px-3 py-2 w-10">방향</th></tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.key} className={`border-t border-slate-100 ${!m.enabled ? "opacity-40" : ""}`}>
                <td className="px-3 py-2"><input type="checkbox" checked={m.enabled} onChange={() => setMetrics((prev) => prev.map((x) => x.key === m.key ? { ...x, enabled: !x.enabled } : x))} className="rounded border-slate-300" /></td>
                <td className="px-3 py-2 font-medium">{m.key}</td>
                <td className="px-3 py-2 font-mono text-xs text-slate-400">{m.name}</td>
                <td className="px-3 py-2"><input type="number" value={m.threshold} onChange={(e) => setMetrics((prev) => prev.map((x) => x.key === m.key ? { ...x, threshold: Number(e.target.value) } : x))} disabled={!m.enabled} className="w-20 rounded border border-slate-200 px-2 py-1 text-sm font-mono disabled:bg-slate-50 disabled:text-slate-300" /></td>
                <td className="px-3 py-2 text-xs text-slate-500">{m.unit}</td>
                <td className="px-3 py-2"><span className={`text-sm font-bold ${m.direction === ">" ? "text-orange-500" : "text-blue-500"}`}>{m.direction === ">" ? "▲" : "▼"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-slate-700">커스텀 메트릭 (CloudWatch)</h4>
        {availableCwMetrics.length > 0 && (
          <button onClick={() => setShowCustom(true)} className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"><Plus size={12} /> 추가</button>
        )}
      </div>

      {customMetrics.length > 0 && (
        <div className="rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <tbody>
              {customMetrics.map((m, idx) => (
                <tr key={idx} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2 font-medium">{m.name}</td>
                  <td className="px-3 py-2"><input type="number" value={m.threshold} onChange={(e) => setCustomMetrics((prev) => prev.map((x, j) => j === idx ? { ...x, threshold: Number(e.target.value) } : x))} className="w-20 rounded border border-slate-200 px-2 py-1 text-sm font-mono" /></td>
                  <td className="px-3 py-2 text-xs text-slate-500">{m.unit}</td>
                  <td className="px-3 py-2"><button onClick={() => setCustomMetrics((prev) => prev.filter((_, j) => j !== idx))} className="text-red-400 hover:text-red-600"><Trash2 size={14} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCustom && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 space-y-3">
          <div>
            <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">CloudWatch 메트릭 선택</label>
            <select value={selectedCwMetric} onChange={(e) => setSelectedCwMetric(e.target.value)} className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none">
              <option value="">메트릭을 선택하세요...</option>
              {availableCwMetrics.filter((m) => !customMetrics.some((c) => c.name === m.name)).map((m) => (
                <option key={m.name} value={m.name}>{m.name} ({m.namespace})</option>
              ))}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <div className="w-24"><label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">임계치</label><input type="number" value={customThreshold} onChange={(e) => setCustomThreshold(Number(e.target.value))} className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm font-mono" /></div>
            <div className="w-16"><label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">단위</label><input type="text" value={customUnit} onChange={(e) => setCustomUnit(e.target.value)} placeholder="%" className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm" /></div>
            <button onClick={addCustomFromDropdown} disabled={!selectedCwMetric} className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">추가</button>
            <button onClick={() => setShowCustom(false)} className="rounded border border-slate-200 px-3 py-1.5 text-sm">취소</button>
          </div>
        </div>
      )}

      {availableCwMetrics.length === 0 && <p className="text-xs text-slate-400">이 리소스 타입에 사용 가능한 추가 CloudWatch 메트릭이 없습니다.</p>}
      {availableCwMetrics.length > 0 && customMetrics.length === 0 && !showCustom && (
        <p className="text-xs text-slate-400">CloudWatch에서 {availableCwMetrics.length}개 추가 메트릭을 사용할 수 있습니다.</p>
      )}
    </>
  );
}
