"use client";

import { useState, useCallback, useEffect } from "react";
import { AlarmRow } from "./AlarmRow";
import type { AlarmConfig } from "@/types";
import type { EditableConfig } from "./AlarmRow";

interface AlarmConfigTableProps {
  resourceId: string;
  initialConfigs: AlarmConfig[];
  monitoringEnabled?: boolean;
  onAddAlarm: () => void;
  /** 임계치·판단 방식 편집 창을 연다 — 표는 읽기 전용이다 */
  onEdit: () => void;
  onRegisterAdd?: (fn: (config: AlarmConfig) => void) => void;
  onRegisterSetAllMonitoring?: (fn: (enabled: boolean) => void) => void;
}

function toEditable(configs: AlarmConfig[]): EditableConfig[] {
  return configs.map((c) => ({ ...c, dirty: false }));
}

export function AlarmConfigTable({
  resourceId,
  initialConfigs,
  monitoringEnabled,
  onAddAlarm,
  onEdit,
  onRegisterAdd,
  onRegisterSetAllMonitoring,
}: AlarmConfigTableProps) {
  // 표는 지금 알람을 보여주기만 한다. 편집은 onEdit 창(PUT /thresholds — 리소스 태그)으로 한다.
  // 예전에는 이 표에서 바로 저장했는데, 중앙 계정 자격 증명으로 알람을 고쳐 고객 계정 리소스에는 맞지 않았고
  // 태그도 EC2만 써서 매시 정합 런이 되돌렸다(2026-11-03).
  const [configs, setConfigs] = useState<EditableConfig[]>(toEditable(initialConfigs));
  const updateConfig = useCallback((_idx: number, _patch: Partial<EditableConfig>) => {}, []);

  const addCustomConfig = useCallback((config: AlarmConfig) => {
    setConfigs((prev) => [...prev, { ...config, dirty: true }]);
  }, []);

  const setAllMonitoring = useCallback((enabled: boolean) => {
    setConfigs((prev) =>
      prev.map((c) => ({ ...c, monitoring: enabled, dirty: true })),
    );
  }, []);

  // Register the add/set-all functions so the parent can call them.
  // 렌더 본문에서 호출하면 React 19 동시성 렌더에서 렌더가 재실행될 때마다
  // 부모 상태를 건드리는 사이드이펙트가 된다 — 커밋 이후(useEffect)에 등록한다.
  useEffect(() => {
    onRegisterAdd?.(addCustomConfig);
  }, [onRegisterAdd, addCustomConfig]);
  useEffect(() => {
    onRegisterSetAllMonitoring?.(setAllMonitoring);
  }, [onRegisterSetAllMonitoring, setAllMonitoring]);

  return (
    <div className="bg-slate-50 rounded-xl overflow-hidden border border-slate-200">
      <div className="px-8 py-6 border-b border-slate-200 flex justify-between items-center bg-white/40">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-headline font-bold">Alarm Configuration</h2>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onEdit}
            className="bg-primary text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-primary/90 transition-all"
          >
            알람 편집
          </button>
          <button
            onClick={onAddAlarm}
            className="text-primary text-sm font-semibold flex items-center gap-2 hover:bg-primary/5 px-4 py-2 rounded-lg transition-all"
          >
            + Add Alarm
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        {monitoringEnabled === false && (
          <div className="bg-amber-50 border-b border-amber-200 px-8 py-3 text-sm text-amber-700 font-medium">
            Monitoring is disabled. Alarms will be activated based on the settings below when monitoring is turned on.
          </div>
        )}
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.1em] text-slate-500 font-bold">
              <th className="pl-8 py-4 w-16">Active</th>
              <th className="px-4 py-4">Metric</th>
              <th className="px-4 py-4">Threshold</th>
              <th className="px-4 py-4">Unit</th>
              <th className="px-4 py-4 text-center">Direction</th>
              <th className="px-4 py-4">Severity</th>
              <th className="px-4 py-4">Source</th>
              <th className="px-4 py-4">State</th>
              <th className="pr-4 py-4 text-right">Current</th>
              <th className="pr-4 py-4"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {configs.map((row, i) => (
              <AlarmRow key={`${row.metric_key}:${row.mount_path ?? ""}`} row={row} index={i} onUpdate={updateConfig} readOnly />
            ))}
          </tbody>
        </table>
      </div>

    </div>
  );
}
