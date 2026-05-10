"use client";

import { useState, useEffect } from "react";
import { X, Check, AlertTriangle, HardDrive } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { fetchAvailableMetrics } from "@/lib/api-functions";
import type { AvailableMetric } from "@/types/api";
import type { AlarmConfig, SeverityLevel } from "@/types";

const SEVERITY_OPTIONS: SeverityLevel[] = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"];
const DEFAULT_THRESHOLD = 80;

interface AlarmFormProps {
  resourceId: string;
  open: boolean;
  onClose: () => void;
  onAdd: (config: AlarmConfig) => void;
}

export function AlarmForm({ resourceId, open, onClose, onAdd }: AlarmFormProps) {
  const [metrics, setMetrics] = useState<AvailableMetric[]>([]);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [selected, setSelected] = useState<AvailableMetric | null>(null);

  const [paths, setPaths] = useState<string[]>([]);
  const [loadingPaths, setLoadingPaths] = useState(false);
  const [mountPath, setMountPath] = useState("");

  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);
  const [severity, setSeverity] = useState<SeverityLevel>("SEV-3");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoadingMetrics(true);
    fetchAvailableMetrics(resourceId)
      .then(setMetrics)
      .catch(() => setMetrics([]))
      .finally(() => setLoadingMetrics(false));
  }, [open, resourceId]);

  useEffect(() => {
    if (!selected?.needs_mount_path) {
      setPaths([]);
      setMountPath("");
      return;
    }
    setLoadingPaths(true);
    fetch(`/api/resources/${encodeURIComponent(resourceId)}/disk-paths`)
      .then((r) => r.json() as Promise<string[]>)
      .then((data) => {
        setPaths(data);
        setMountPath(data[0] ?? "");
      })
      .catch(() => setPaths([]))
      .finally(() => setLoadingPaths(false));
  }, [selected, resourceId]);

  if (!open) return null;

  const canSubmit = (() => {
    if (!selected || submitting) return false;
    if (selected.needs_mount_path && !mountPath) return false;
    return true;
  })();

  const handleSubmit = async () => {
    if (!selected) return;
    setSubmitting(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        metric_name: selected.metric_name,
        threshold,
        severity,
      };
      if (selected.needs_mount_path) body.mount_path = mountPath;

      const res = await fetch(
        `/api/resources/${encodeURIComponent(resourceId)}/alarms`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { message?: string };
        setError(data.message ?? "알람 생성에 실패했습니다");
        return;
      }
      onAdd({
        metric_key: selected.needs_mount_path
          ? `disk_used_percent:${mountPath}`
          : `custom-${selected.metric_name}`,
        metric_name: selected.metric_name,
        namespace: selected.namespace,
        threshold,
        unit: selected.unit ?? "Count",
        direction: selected.direction,
        severity,
        source: selected.needs_mount_path ? "System" : "Custom",
        state: "OFF",
        current_value: null,
        monitoring: true,
        ...(selected.needs_mount_path ? { mount_path: mountPath } : {}),
      });
      resetForm();
      onClose();
    } catch {
      setError("요청에 실패했습니다");
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    setSelected(null);
    setMountPath("");
    setPaths([]);
    setThreshold(DEFAULT_THRESHOLD);
    setSeverity("SEV-3");
    setError("");
  };

  return (
    <div className="border border-primary/20 bg-primary/5 rounded-xl p-6 space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-headline font-bold text-sm">Add Alarm</h3>
        <Button variant="ghost" onClick={onClose} icon={<X size={16} />} />
      </div>

      <div>
        <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
          Metric
        </label>
        {loadingMetrics ? (
          <div className="h-9 bg-white animate-pulse rounded-lg" />
        ) : (
          <select
            value={selected ? `${selected.metric_name}|${selected.namespace}` : ""}
            onChange={(e) => {
              const [name, ns] = e.target.value.split("|");
              const m = metrics.find((x) => x.metric_name === name && x.namespace === ns);
              setSelected(m ?? null);
            }}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none"
          >
            <option value="">Select a metric...</option>
            {metrics.map((m) => (
              <option
                key={`${m.metric_name}-${m.namespace}`}
                value={`${m.metric_name}|${m.namespace}`}
              >
                {m.metric_name} ({m.namespace})
                {m.needs_mount_path ? " — per mount path" : ""}
              </option>
            ))}
          </select>
        )}
        {!loadingMetrics && metrics.length === 0 && (
          <div className="mt-1 flex items-center gap-1.5 text-xs text-amber-700">
            <AlertTriangle size={14} />
            <span>이 리소스가 보고 중인 CloudWatch 메트릭이 없습니다.</span>
          </div>
        )}
        {selected && (
          <div className="mt-1 flex items-center gap-1.5 text-xs text-green-700">
            <Check size={14} />
            <span>Metric found</span>
          </div>
        )}
      </div>

      {selected?.needs_mount_path && (
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1 flex items-center gap-1.5">
            <HardDrive size={12} className="text-primary" />
            Mount Path
          </label>
          {loadingPaths ? (
            <div className="h-9 bg-white animate-pulse rounded-lg" />
          ) : paths.length === 0 ? (
            <p className="text-xs text-slate-400 py-2">
              CWAgent 디스크 메트릭을 찾을 수 없습니다. 인스턴스에 CWAgent가 설치되어 있는지 확인하세요.
            </p>
          ) : (
            <select
              value={mountPath}
              onChange={(e) => setMountPath(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none font-mono"
            >
              {paths.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
            Threshold {selected?.unit ? `(${selected.unit})` : ""}
          </label>
          <input
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono bg-white focus:ring-1 focus:ring-primary outline-none"
          />
        </div>
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
            Severity
          </label>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as SeverityLevel)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none"
          >
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="flex gap-2">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting ? "생성 중..." : "Create Alarm"}
        </button>
        <button
          onClick={onClose}
          className="border border-slate-200 text-slate-600 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
