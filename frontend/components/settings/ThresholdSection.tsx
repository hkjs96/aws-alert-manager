"use client";

import { useState, useEffect, useMemo } from "react";
import { Settings, Save } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { getMockThresholdOverrides } from "@/lib/mock-data";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";
import type { ThresholdOverride } from "@/types/api";

export function ThresholdSection() {
  const { showToast } = useToast();
  const [activeType, setActiveType] = useState<string>(SUPPORTED_RESOURCE_TYPES[0]);
  const [thresholds, setThresholds] = useState<ThresholdOverride[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [dirtyTabs, setDirtyTabs] = useState<Set<string>>(new Set());
  const [initialThresholds, setInitialThresholds] = useState<ThresholdOverride[]>([]);

  useEffect(() => {
    // Simulate GET /api/thresholds/{type}
    const data = getMockThresholdOverrides(activeType);
    setThresholds(data);
    setInitialThresholds(data);
  }, [activeType]);

  // Track unsaved changes per tab
  const isCurrentTabDirty = useMemo(() => {
    if (thresholds.length !== initialThresholds.length) return true;
    return thresholds.some((t, idx) => {
      const initial = initialThresholds[idx];
      return initial && (t.customer_override !== initial.customer_override);
    });
  }, [thresholds, initialThresholds]);

  useEffect(() => {
    if (isCurrentTabDirty) {
      setDirtyTabs((prev) => new Set([...prev, activeType]));
    } else {
      setDirtyTabs((prev) => {
        const next = new Set(prev);
        next.delete(activeType);
        return next;
      });
    }
  }, [isCurrentTabDirty, activeType]);

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
      // Mark current tab as saved
      setInitialThresholds(thresholds);
      setDirtyTabs((prev) => {
        const next = new Set(prev);
        next.delete(activeType);
        return next;
      });
    } catch {
      showToast("error", "Failed to save thresholds.");
    } finally {
      setIsSaving(false);
    }
  };

  // Helper function to format condition string
  const formatCondition = (direction: ">" | "<", unit: string, systemDefault: number): string => {
    const directionDisplay = direction === ">" ? ">=" : "<=";
    return `${directionDisplay} ${systemDefault}${unit ? " " + unit : ""}`;
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-soft overflow-hidden">
      {/* Section header */}
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Settings size={18} className="text-primary" /> Default Thresholds
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Configure alarm threshold policies by resource type</p>
        </div>
      </div>

      {/* Resource type tabs — horizontal scroll */}
      <div className="px-6 py-4 border-b border-slate-100 overflow-x-auto">
        <div className="flex gap-2 pb-0 scrollbar-thin">
          {SUPPORTED_RESOURCE_TYPES.map((type) => {
            const hasUnsavedChanges = dirtyTabs.has(type);
            return (
              <Button
                key={type}
                variant={activeType === type ? "primary" : "secondary"}
                size="sm"
                onClick={() => setActiveType(type)}
                className="gap-2"
              >
                {type}
                {hasUnsavedChanges && (
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
                )}
              </Button>
            );
          })}
        </div>
      </div>

      {/* Threshold table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Metric</th>
              <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Condition</th>
              <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">System Default</th>
              <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Customer Override</th>
              <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Active Level</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {thresholds.map((t) => {
              const isOverridden = t.customer_override !== null;
              const overridePercent = isOverridden
                ? Math.round(((t.customer_override! - t.system_default) / t.system_default) * 100)
                : 0;
              const barWidth = Math.min(100, Math.abs(overridePercent));
              const isIncreased = overridePercent > 0;

              return (
                <tr key={t.metric_key} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-semibold text-slate-900">{t.metric_key}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{formatCondition(t.direction, t.unit, t.system_default)}</td>
                  <td className="px-4 py-3 font-mono text-slate-600">{t.system_default}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1">
                      <input
                        type="number"
                        value={t.customer_override ?? ""}
                        onChange={(e) => handleOverrideChange(t.metric_key, e.target.value)}
                        placeholder="—"
                        className="w-24 bg-white border border-slate-200 rounded px-2 py-1 text-sm font-mono focus:ring-2 focus:ring-primary/20 outline-none"
                      />
                      {isOverridden && (
                        <div className="w-24 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full transition-all ${isIncreased ? "bg-blue-500" : "bg-orange-500"}`}
                            style={{ width: `${barWidth}%` }}
                          />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
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

      {/* Sticky save button */}
      <div className="sticky bottom-0 bg-white border-t border-slate-200 px-6 py-4 flex justify-end">
        <LoadingButton
          isLoading={isSaving}
          onClick={handleSave}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 shadow-lg shadow-primary/20 hover:brightness-110 transition-all"
        >
          <Save size={14} /> Save Changes
        </LoadingButton>
        {/* Note: Save button kept as LoadingButton to preserve custom styling */}
      </div>
    </div>
  );
}
