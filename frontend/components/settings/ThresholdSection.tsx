"use client";

import { useState, useEffect } from "react";
import { Settings, Save } from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { getMockThresholdOverrides } from "@/lib/mock-data";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";
import type { ThresholdOverride } from "@/types/api";

export function ThresholdSection() {
  const { showToast } = useToast();
  const [activeType, setActiveType] = useState(SUPPORTED_RESOURCE_TYPES[0]);
  const [thresholds, setThresholds] = useState<ThresholdOverride[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    // Simulate GET /api/thresholds/{type}
    const data = getMockThresholdOverrides(activeType);
    setThresholds(data);
  }, [activeType]);

  const handleOverrideChange = (metricKey: string, value: string) => {
    setThresholds((prev) =>
      prev.map((t) =>
        t.metric_key === metricKey
          ? { ...t, customer_override: value === "" ? null : Number(value) }
          : t,
      ),
    );
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      // Simulate PUT /api/thresholds/{type}
      await new Promise((resolve) => setTimeout(resolve, 800));
      showToast("success", `${activeType} thresholds saved.`);
    } catch {
      showToast("error", "Failed to save thresholds.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-xl p-8 shadow-soft border border-slate-200">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-headline font-semibold flex items-center gap-2">
          <Settings size={20} className="text-primary" /> Default Thresholds
        </h2>
        <LoadingButton
          isLoading={isSaving}
          onClick={handleSave}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 shadow-lg shadow-primary/20 hover:brightness-110 transition-all"
        >
          <Save size={14} /> Save Changes
        </LoadingButton>
      </div>

      {/* Resource type tabs — horizontal scroll */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-6 scrollbar-thin">
        {SUPPORTED_RESOURCE_TYPES.map((type) => (
          <button
            key={type}
            onClick={() => setActiveType(type)}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition-all ${
              activeType === type
                ? "bg-primary text-white shadow-sm"
                : "bg-slate-100 text-slate-500 hover:text-slate-700 hover:bg-slate-200"
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {/* Threshold table */}
      <div className="bg-slate-50 rounded-lg overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-slate-400 text-[11px] font-bold uppercase tracking-wider">
              <th className="py-3 px-6">Metric</th>
              <th className="py-3 px-6">Direction</th>
              <th className="py-3 px-6">Unit</th>
              <th className="py-3 px-6">System Default</th>
              <th className="py-3 px-6">Customer Override</th>
              <th className="py-3 px-6">Active Level</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {thresholds.map((t) => {
              const isOverridden = t.customer_override !== null;
              return (
                <tr key={t.metric_key} className="hover:bg-white transition-colors">
                  <td className="py-3 px-6 font-semibold">{t.metric_key}</td>
                  <td className="py-3 px-6 font-mono text-xs">{t.direction}</td>
                  <td className="py-3 px-6 text-slate-500">{t.unit}</td>
                  <td className="py-3 px-6 font-mono">{t.system_default}</td>
                  <td className="py-3 px-6">
                    <input
                      type="number"
                      value={t.customer_override ?? ""}
                      onChange={(e) => handleOverrideChange(t.metric_key, e.target.value)}
                      placeholder="—"
                      className="w-24 bg-white border border-slate-200 rounded px-2 py-1 text-sm font-mono focus:ring-2 focus:ring-primary/20 outline-none"
                    />
                  </td>
                  <td className="py-3 px-6">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        isOverridden
                          ? "bg-blue-100 text-blue-700"
                          : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          isOverridden ? "bg-blue-500" : "bg-slate-400"
                        }`}
                      />
                      {isOverridden ? "Customer" : "System"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
