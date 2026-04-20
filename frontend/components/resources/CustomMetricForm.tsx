"use client";

import { useState, useEffect } from "react";
import { X, Check, AlertTriangle } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { fetchAvailableMetrics } from "@/lib/api-functions";
import type { AvailableMetric } from "@/types/api";
import type { AlarmConfig } from "@/types";

interface CustomMetricFormProps {
  resourceId: string;
  open: boolean;
  onClose: () => void;
  onAdd: (config: AlarmConfig) => void;
}

export function CustomMetricForm({ resourceId, open, onClose, onAdd }: CustomMetricFormProps) {
  const [metrics, setMetrics] = useState<AvailableMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<AvailableMetric | null>(null);
  const [threshold, setThreshold] = useState(80);
  const [unit, setUnit] = useState("Count");
  const [direction, setDirection] = useState<">" | ">=" | "<" | "<=">(">");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetchAvailableMetrics(resourceId)
      .then(setMetrics)
      .catch(() => setMetrics([]))
      .finally(() => setLoading(false));
  }, [open, resourceId]);

  if (!open) return null;

  const handleSubmit = () => {
    if (!selected) return;
    const config: AlarmConfig = {
      metric_key: `custom-${selected.metric_name}`,
      metric_name: selected.metric_name,
      namespace: selected.namespace,
      threshold,
      unit,
      direction,
      severity: "SEV-3",
      source: "Custom",
      state: "OFF",
      current_value: null,
      monitoring: true,
    };
    onAdd(config);
    resetForm();
    onClose();
  };

  const resetForm = () => {
    setSelected(null);
    setThreshold(80);
    setUnit("Count");
    setDirection(">");
  };

  // Simple existence check: metric is "found" if it's in the available list
  const metricExists = selected !== null;

  return (
    <div className="border border-primary/20 bg-primary/5 rounded-xl p-6 space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-headline font-bold text-sm">Add Custom Metric</h3>
        <Button variant="ghost" onClick={onClose} icon={<X size={16} />} />
      </div>

      {/* Metric dropdown */}
      <div>
        <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
          Metric
        </label>
        {loading ? (
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
              <option key={`${m.metric_name}-${m.namespace}`} value={`${m.metric_name}|${m.namespace}`}>
                {m.metric_name} ({m.namespace})
              </option>
            ))}
          </select>
        )}
        {selected && (
          <div className="mt-1 flex items-center gap-1.5 text-xs">
            {metricExists ? (
              <>
                <Check size={14} className="text-green-600" />
                <span className="text-green-700">Metric found</span>
              </>
            ) : (
              <>
                <AlertTriangle size={14} className="text-amber-600" />
                <span className="text-amber-700">Metric not found in CloudWatch</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Threshold + Unit + Direction */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
            Threshold
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
            Unit
          </label>
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none"
          >
            {["Percent", "Bytes", "Kilobytes", "Megabytes", "Gigabytes", "Terabytes",
              "Count", "Count/Second",
              "Seconds", "Milliseconds", "Microseconds",
              "Bits", "Bits/Second", "Bytes/Second",
              "None"].map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider block mb-1">
            Direction
          </label>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as ">" | ">=" | "<" | "<=")}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-1 focus:ring-primary outline-none"
          >
            <option value=">">&gt; (Above)</option>
            <option value=">=">&gt;= (Above or Equal)</option>
            <option value="<">&lt; (Below)</option>
            <option value="<=">&lt;= (Below or Equal)</option>
          </select>
        </div>
      </div>

      <Button
        variant="primary"
        onClick={handleSubmit}
        disabled={!selected}
      >
        Add Metric
      </Button>
    </div>
  );
}
