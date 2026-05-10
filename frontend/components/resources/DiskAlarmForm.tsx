"use client";

import { useState, useEffect } from "react";
import { X, HardDrive } from "lucide-react";
import type { AlarmConfig, SeverityLevel } from "@/types";

const SEVERITY_OPTIONS: SeverityLevel[] = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"];

interface DiskAlarmFormProps {
  resourceId: string;
  open: boolean;
  onClose: () => void;
  onAdd: (config: AlarmConfig) => void;
}

export function DiskAlarmForm({ resourceId, open, onClose, onAdd }: DiskAlarmFormProps) {
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState("");
  const [threshold, setThreshold] = useState(80);
  const [severity, setSeverity] = useState<SeverityLevel>("SEV-3");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError("");
    fetch(`/api/resources/${encodeURIComponent(resourceId)}/disk-paths`)
      .then((r) => r.json() as Promise<string[]>)
      .then((data) => {
        setPaths(data);
        if (data.length > 0) setSelectedPath(data[0]);
      })
      .catch(() => setPaths([]))
      .finally(() => setLoading(false));
  }, [open, resourceId]);

  if (!open) return null;

  const handleSubmit = async () => {
    if (!selectedPath) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`/api/resources/${encodeURIComponent(resourceId)}/alarms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          metric_name: "disk_used_percent",
          threshold,
          mount_path: selectedPath,
          severity,
        }),
      });
      if (!res.ok) {
        const data = (await res.json()) as { message?: string };
        setError(data.message ?? "알람 생성에 실패했습니다");
        return;
      }
      onAdd({
        metric_key: `disk_used_percent:${selectedPath}`,
        metric_name: "disk_used_percent",
        namespace: "CWAgent",
        threshold,
        unit: "Percent",
        direction: ">",
        severity,
        source: "System",
        state: "OFF",
        current_value: null,
        monitoring: true,
        mount_path: selectedPath,
      });
      onClose();
    } catch {
      setError("요청에 실패했습니다");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="border border-primary/20 bg-primary/5 rounded-xl p-6 space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <HardDrive size={16} className="text-primary" />
          <h3 className="font-headline font-bold text-sm">Add Disk Alarm</h3>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
          <X size={16} />
        </button>
      </div>

      <div>
        <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
          Mount Path
        </label>
        {loading ? (
          <div className="h-9 bg-white animate-pulse rounded-lg" />
        ) : paths.length === 0 ? (
          <p className="text-xs text-slate-400 py-2">
            CWAgent 디스크 메트릭을 찾을 수 없습니다. 인스턴스에 CWAgent가 설치되어 있는지 확인하세요.
          </p>
        ) : (
          <select
            value={selectedPath}
            onChange={(e) => setSelectedPath(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none font-mono"
          >
            {paths.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
            Threshold (%)
          </label>
          <input
            type="number"
            value={threshold}
            min={1}
            max={100}
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
          disabled={!selectedPath || submitting || loading}
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
