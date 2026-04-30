"use client";

import { useState, useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { Settings, Save } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { getMockThresholdOverrides } from "@/lib/mock-data";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";
import { fetchThresholds, saveThresholds } from "@/lib/api-functions";
import type { ThresholdOverride } from "@/types/api";

const USE_REAL_API = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL);

export function ThresholdSection() {
  const { showToast } = useToast();
  const searchParams = useSearchParams();
  const customerId = searchParams.get("customer_id") ?? "";

  const [activeType, setActiveType] = useState<string>(SUPPORTED_RESOURCE_TYPES[0]);
  const [thresholds, setThresholds] = useState<ThresholdOverride[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [dirtyTabs, setDirtyTabs] = useState<Set<string>>(new Set());
  const [initialThresholds, setInitialThresholds] = useState<ThresholdOverride[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        let data: ThresholdOverride[];
        if (USE_REAL_API) {
          data = await fetchThresholds(activeType, { customer_id: customerId });
        } else {
          data = getMockThresholdOverrides(activeType);
        }
        if (!cancelled) {
          setThresholds(data);
          setInitialThresholds(data);
        }
      } catch {
        if (!cancelled) showToast("error", `${activeType} 임계치 로드에 실패했습니다.`);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [activeType, customerId]);  // eslint-disable-line react-hooks/exhaustive-deps

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
      if (USE_REAL_API) {
        await saveThresholds(activeType, thresholds, customerId || undefined);
      } else {
        // 로컬 mock: 지연 시뮬레이션
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
      showToast("success", `${activeType} thresholds saved.`);
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

  const formatCondition = (direction: ">" | "<", unit: string, systemDefault: number): string => {
    const dir = direction === ">" ? ">=" : "<=";
    return `${dir} ${systemDefault}${unit ? " " + unit : ""}`;
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-soft overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Settings size={18} className="text-primary" /> Default Thresholds
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Configure alarm threshold policies by resource type</p>
        </div>
      </div>

      {/* Resource type tabs */}
      <div className="px-6 py-4 border-b border-slate-100 overflow-x-auto">
        <div className="flex gap-2 scrollbar-thin">
          {SUPPORTED_RESOURCE_TYPES.map((type) => (
            <Button
              key={type}
              variant={activeType === type ? "primary" : "secondary"}
              size="sm"
              onClick={() => setActiveType(type)}
              className="gap-2"
            >
              {type}
              {dirtyTabs.has(type) && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
              )}
            </Button>
          ))}
        </div>
      </div>

      {/* Threshold table */}
      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="px-6 py-8 text-center text-sm text-slate-400">로딩 중...</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Metric</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Condition</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">System Default</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Customer Override</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Active Level</th>
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
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">
                      {formatCondition(t.direction, t.unit, t.system_default)}
                    </td>
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
                          isOverridden ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${isOverridden ? "bg-blue-500" : "bg-slate-400"}`} />
                        {isOverridden ? "Customer" : "System"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="sticky bottom-0 bg-white border-t border-slate-200 px-6 py-4 flex justify-end">
        <LoadingButton
          isLoading={isSaving}
          onClick={handleSave}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 shadow-lg shadow-primary/20 hover:brightness-110 transition-all"
        >
          <Save size={14} /> Save Changes
        </LoadingButton>
      </div>
    </div>
  );
}
