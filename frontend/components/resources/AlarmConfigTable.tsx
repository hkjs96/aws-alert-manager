"use client";

import { useState } from "react";
import type { AlarmConfig } from "@/types";
import { MonitoringToggle } from "@/components/shared/MonitoringToggle";
import { DirectionIcon } from "@/components/shared/DirectionIcon";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { SourceBadge } from "@/components/shared/SourceBadge";
import { AlarmStatusPill } from "@/components/shared/AlarmStatusPill";

interface AlarmConfigTableProps {
  alarms: AlarmConfig[];
  onChange: (alarms: AlarmConfig[]) => void;
}

export function AlarmConfigTable({ alarms, onChange }: AlarmConfigTableProps) {
  const updateAlarm = (index: number, updates: Partial<AlarmConfig>) => {
    const next = alarms.map((a, i) => (i === index ? { ...a, ...updates } : a));
    onChange(next);
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
          <tr>
            <th className="w-16 px-4 py-3">모니터</th>
            <th className="px-4 py-3">메트릭</th>
            <th className="px-4 py-3">CW 메트릭</th>
            <th className="w-24 px-4 py-3">임계치</th>
            <th className="w-16 px-4 py-3">단위</th>
            <th className="w-12 px-4 py-3">방향</th>
            <th className="w-20 px-4 py-3">등급</th>
            <th className="w-20 px-4 py-3">소스</th>
            <th className="w-20 px-4 py-3">상태</th>
            <th className="w-24 px-4 py-3 text-right">현재 값</th>
          </tr>
        </thead>
        <tbody>
          {alarms.map((alarm, i) => (
            <tr
              key={`${alarm.metric_key}-${alarm.mount_path ?? ""}`}
              className={`border-b border-slate-100 ${!alarm.monitoring ? "opacity-50" : ""} ${i % 2 === 1 ? "bg-slate-50/50" : ""}`}
            >
              <td className="px-4 py-3">
                <MonitoringToggle
                  enabled={alarm.monitoring}
                  onChange={(v) => updateAlarm(i, { monitoring: v })}
                />
              </td>
              <td className="px-4 py-3 font-medium">
                {alarm.metric_key}
                {alarm.mount_path && (
                  <span className="ml-1 text-xs text-slate-400">({alarm.mount_path})</span>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{alarm.metric_name}</td>
              <td className="px-4 py-3">
                <input
                  type="number"
                  value={alarm.threshold}
                  onChange={(e) => updateAlarm(i, { threshold: Number(e.target.value) })}
                  disabled={!alarm.monitoring}
                  className="w-20 rounded-md border border-slate-200 px-2 py-1 text-sm font-mono disabled:bg-slate-50 disabled:text-slate-400"
                />
              </td>
              <td className="px-4 py-3 text-xs text-slate-500">{alarm.unit}</td>
              <td className="px-4 py-3"><DirectionIcon direction={alarm.direction} /></td>
              <td className="px-4 py-3"><SeverityBadge severity={alarm.severity} /></td>
              <td className="px-4 py-3"><SourceBadge source={alarm.source} /></td>
              <td className="px-4 py-3"><AlarmStatusPill state={alarm.monitoring ? alarm.state : "OFF"} /></td>
              <td className="px-4 py-3 text-right font-mono text-xs">
                {alarm.current_value !== null ? (
                  <span className={
                    alarm.monitoring && alarm.state === "ALARM" ? "text-red-600 font-medium" : "text-slate-600"
                  }>
                    {alarm.current_value}{alarm.unit ? alarm.unit : ""}
                  </span>
                ) : (
                  <span className="text-slate-300">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
