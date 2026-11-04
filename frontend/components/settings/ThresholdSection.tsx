"use client";

import { useState, useEffect, useMemo } from "react";
import { Settings, Save } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { FRONTEND_INTEGRATION_RESOURCE_TYPES } from "@/lib/constants";
import { fetchResources, fetchResourceThresholds, fetchThresholds, saveThresholds } from "@/lib/api-functions";
import { defaultImpact, runPool, type DefaultImpact } from "@/lib/threshold-edit";
import type { ThresholdMetric, ThresholdOverride } from "@/types/api";

/** 고객사의 이 타입 리소스(모니터링 켠 것) 전부와 각자의 임계치 */
async function loadCustomerResources(type: string, customerId: string) {
  const resources: { id: string; name: string }[] = [];
  for (let page = 1; ; page++) {
    const data = await fetchResources({ customer_id: customerId, resource_type: type, monitoring: true, page, page_size: 100 });
    resources.push(...data.items.map((r) => ({ id: r.id, name: r.name || r.id })));
    if (data.items.length < 100) break;
  }
  const loaded: { name: string; metrics: ThresholdMetric[] }[] = [];
  const failed: string[] = [];
  await runPool(resources, async (r) => {
    const data = await fetchResourceThresholds(r.id);
    loaded.push({ name: r.name, metrics: data.metrics });
  }, 3, (r, error) => { if (error) failed.push(r.name); });
  return { loaded, failed };
}

function NameList({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  const shown = names.slice(0, 5).join(", ");
  return <span className="text-slate-400"> ({shown}{names.length > 5 ? ` 외 ${names.length - 5}개` : ""})</span>;
}

/** `customerId`: 상단 글로벌 필터가 고른 고객사(URL ?customer=). 비면 전역 기본값을 편집한다. */
export function ThresholdSection({ customerId = "" }: { customerId?: string }) {
  const { showToast } = useToast();

  const [activeType, setActiveType] = useState<string>(FRONTEND_INTEGRATION_RESOURCE_TYPES[0]);
  const [thresholds, setThresholds] = useState<ThresholdOverride[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [dirtyTabs, setDirtyTabs] = useState<Set<string>>(new Set());
  const [initialThresholds, setInitialThresholds] = useState<ThresholdOverride[]>([]);
  const [impact, setImpact] = useState<{ rows: { metric: string; before: string; after: string; result: DefaultImpact }[]; failed: string[] } | null>(null);
  const [isImpactLoading, setIsImpactLoading] = useState(false);

  // 값이 바뀌면 이전 영향 보기는 맞지 않는다
  useEffect(() => { setImpact(null); }, [thresholds, activeType, customerId]);

  const changedMetrics = useMemo(
    () => thresholds.filter((t) => {
      const initial = initialThresholds.find((i) => i.metric_key === t.metric_key);
      return initial && initial.customer_override !== t.customer_override;
    }),
    [thresholds, initialThresholds],
  );

  const handleImpact = async () => {
    setIsImpactLoading(true);
    try {
      const { loaded, failed } = await loadCustomerResources(activeType, customerId);
      const rows = changedMetrics.map((t) => {
        const initial = initialThresholds.find((i) => i.metric_key === t.metric_key)!;
        const fmt = (v: number | null) => (v === null ? `시스템 ${t.system_default}` : String(v));
        return { metric: t.metric_key, before: fmt(initial.customer_override), after: fmt(t.customer_override), result: defaultImpact(t.metric_key, loaded) };
      });
      setImpact({ rows, failed });
    } catch {
      showToast("error", "리소스 목록을 불러오지 못했습니다.");
    } finally {
      setIsImpactLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        const data = await fetchThresholds(activeType, { customer_id: customerId });
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
    const num = value === "" ? null : Number(value);
    if (num !== null && num < 0) return; // UI 1단계: 음수 입력 차단
    setThresholds((prev) =>
      prev.map((t) =>
        t.metric_key === metricKey ? { ...t, customer_override: num } : t,
      ),
    );
  };

  const handleSave = async () => {
    // 2단계: 제출 전 음수 검증
    const invalid = thresholds.filter((t) => t.customer_override !== null && t.customer_override < 0);
    if (invalid.length > 0) {
      showToast("error", `Threshold must be 0 or greater: ${invalid.map((t) => t.metric_key).join(", ")}`);
      return;
    }
    setIsSaving(true);
    try {
      await saveThresholds(activeType, thresholds, customerId || undefined);
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
          {FRONTEND_INTEGRATION_RESOURCE_TYPES.map((type) => (
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
                          min="0"
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

      {impact && (
        <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 text-sm space-y-2" data-testid="default-impact">
          {impact.rows.map((row) => (
            <div key={row.metric}>
              <span className="font-semibold text-slate-800">{row.metric}</span>{" "}
              <span className="font-mono text-slate-500">{row.before} → {row.after}</span>
              <div className="text-slate-600">
                {row.result.applies.length}개에 적용
                {row.result.keeps.length > 0 && <> · {row.result.keeps.length}개는 개별값 유지<NameList names={row.result.keeps} /></>}
                {row.result.skips.length > 0 && <> · {row.result.skips.length}개는 알람 꺼짐/없음</>}
              </div>
            </div>
          ))}
          {impact.failed.length > 0 && (
            <div className="text-amber-700">{impact.failed.length}개 리소스는 확인하지 못했습니다<NameList names={impact.failed} /></div>
          )}
          <div className="text-xs text-slate-400">모니터링을 켠 리소스 기준. 저장한 값은 다음 정기 동기화 때 알람에 반영됩니다.</div>
        </div>
      )}

      <div className="sticky bottom-0 bg-white border-t border-slate-200 px-6 py-4 flex justify-end items-center gap-3">
        {!customerId ? (
          <span className="text-xs text-slate-400">고객사를 선택하면 영향을 볼 수 있습니다</span>
        ) : (
          <LoadingButton
            isLoading={isImpactLoading}
            onClick={handleImpact}
            disabled={changedMetrics.length === 0}
            className="border border-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-50 disabled:opacity-40"
          >
            변경 내용 보기
          </LoadingButton>
        )}
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
