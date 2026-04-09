"use client";

import { useState, useCallback } from "react";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { AlarmRow } from "./AlarmRow";
import { saveAlarmConfigs } from "@/lib/api-functions";
import type { AlarmConfig } from "@/types";
import type { EditableConfig } from "./AlarmRow";

interface AlarmConfigTableProps {
  resourceId: string;
  initialConfigs: AlarmConfig[];
  onAddCustomMetric: () => void;
  onRegisterAdd?: (fn: (config: AlarmConfig) => void) => void;
}

function toEditable(configs: AlarmConfig[]): EditableConfig[] {
  return configs.map((c) => ({ ...c, dirty: false }));
}

export function AlarmConfigTable({
  resourceId,
  initialConfigs,
  onAddCustomMetric,
  onRegisterAdd,
}: AlarmConfigTableProps) {
  const { showToast } = useToast();
  const [configs, setConfigs] = useState<EditableConfig[]>(toEditable(initialConfigs));
  const [originals] = useState<AlarmConfig[]>(initialConfigs);
  const [isSaving, setIsSaving] = useState(false);

  const hasDirty = configs.some((c) => c.dirty);

  const updateConfig = useCallback(
    (idx: number, patch: Partial<EditableConfig>) => {
      setConfigs((prev) =>
        prev.map((c, i) => (i === idx ? { ...c, ...patch, dirty: true } : c)),
      );
    },
    [],
  );

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await saveAlarmConfigs(resourceId, {
        configs: configs
          .filter((c) => c.dirty)
          .map((c) => ({
            metric_key: c.metric_key,
            threshold: c.threshold,
            monitoring: c.monitoring,
          })),
      });
      showToast("success", "알람 설정이 저장되었습니다.");
      setConfigs((prev) => prev.map((c) => ({ ...c, dirty: false })));
    } catch {
      showToast("error", "알람 설정 저장에 실패했습니다.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setConfigs(toEditable(originals));
    showToast("info", "시스템 기본값으로 복원되었습니다.");
  };

  const addCustomConfig = useCallback((config: AlarmConfig) => {
    setConfigs((prev) => [...prev, { ...config, dirty: true }]);
  }, []);

  // Register the add function so parent can call it
  if (onRegisterAdd) onRegisterAdd(addCustomConfig);

  return (
    <div className="bg-slate-50 rounded-xl overflow-hidden border border-slate-200">
      <div className="px-8 py-6 border-b border-slate-200 flex justify-between items-center bg-white/40">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-headline font-bold">Alarm Configuration</h2>
          {hasDirty && (
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" title="Unsaved changes" />
          )}
        </div>
        <button
          onClick={onAddCustomMetric}
          className="text-primary text-sm font-semibold flex items-center gap-2 hover:bg-primary/5 px-4 py-2 rounded-lg transition-all"
        >
          + Add Custom Metric
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.1em] text-slate-500 font-bold">
              <th className="pl-8 py-4 w-16">Monitor</th>
              <th className="px-4 py-4">Metric</th>
              <th className="px-4 py-4">Threshold</th>
              <th className="px-4 py-4">Unit</th>
              <th className="px-4 py-4 text-center">Direction</th>
              <th className="px-4 py-4">Severity</th>
              <th className="px-4 py-4">Source</th>
              <th className="px-4 py-4">State</th>
              <th className="pr-8 py-4 text-right">Current Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {configs.map((row, i) => (
              <AlarmRow key={row.metric_key} row={row} index={i} onUpdate={updateConfig} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Action buttons */}
      <div className="px-8 py-4 border-t border-slate-200 bg-white/40 flex gap-3">
        <LoadingButton
          isLoading={isSaving}
          disabled={!hasDirty}
          onClick={handleSave}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
        >
          Save Changes
        </LoadingButton>
        <button
          onClick={handleReset}
          className="border border-slate-300 text-slate-600 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-50"
        >
          Reset to Defaults
        </button>
        <button
          disabled
          className="border border-slate-200 text-slate-400 px-4 py-2 rounded-lg text-sm font-semibold cursor-not-allowed"
        >
          Apply Customer Defaults
        </button>
      </div>
    </div>
  );
}
