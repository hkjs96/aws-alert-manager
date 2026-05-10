"use client";

import { useState, useCallback, useRef } from "react";
import { ResourceHeader } from "./ResourceHeader";
import { AlarmConfigTable } from "./AlarmConfigTable";
import { CustomMetricForm } from "./CustomMetricForm";
import type { Resource, AlarmConfig } from "@/types";

interface ResourceDetailClientProps {
  resource: Resource;
  alarmConfigs: AlarmConfig[];
}

export function ResourceDetailClient({ resource, alarmConfigs }: ResourceDetailClientProps) {
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [monitoring, setMonitoring] = useState(resource.monitoring);
  const addConfigRef = useRef<((config: AlarmConfig) => void) | null>(null);
  const setAllMonitoringRef = useRef<((enabled: boolean) => void) | null>(null);

  const handleMonitoringChange = useCallback((newState: boolean) => {
    setMonitoring(newState);
    setAllMonitoringRef.current?.(newState);
  }, []);

  const handleAddCustomMetric = useCallback((config: AlarmConfig) => {
    addConfigRef.current?.(config);
  }, []);

  // Health Map: Build metric grid from alarm configs
  const healthItems = alarmConfigs.map((config) => ({
    metricName: config.metric_name || config.metric_key,
    state: config.state || "OK" as const,
    enabled: config.monitoring ?? true,
  }));

  const hasHealthData = alarmConfigs.length > 0;

  return (
    <>
      <ResourceHeader resource={resource} onMonitoringChange={handleMonitoringChange} />

      {/* Health Map Section */}
      {hasHealthData && (
        <div className="bg-white rounded-xl p-6 shadow-soft border border-slate-200 mb-6">
          <div className="mb-4">
            <h3 className="text-lg font-semibold text-slate-900">Health Map</h3>
            <p className="text-sm text-slate-500 mt-1">Real-time metric status overview</p>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {healthItems.map((item) => (
              <div
                key={item.metricName}
                className={`rounded-lg p-2.5 border text-center cursor-pointer hover:opacity-80 transition-opacity ${
                  !item.enabled
                    ? "bg-slate-50 border-slate-200"
                    : item.state === "ALARM"
                      ? "bg-red-50 border-red-200"
                      : item.state === "INSUFFICIENT"
                        ? "bg-amber-50 border-amber-200"
                        : "bg-green-50 border-green-200"
                }`}
              >
                <div className="text-lg mb-1">
                  {!item.enabled
                    ? "⚫"
                    : item.state === "ALARM"
                      ? "🔴"
                      : item.state === "INSUFFICIENT"
                        ? "🟡"
                        : "🟢"}
                </div>
                <div className="text-[10px] font-semibold text-slate-700 leading-tight">
                  {item.metricName}
                </div>
                <div className="text-[9px] text-slate-400 mt-0.5">
                  {!item.enabled ? "Disabled" : item.state === "ALARM" ? "ALARM" : item.state === "INSUFFICIENT" ? "데이터 부족" : "OK"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <AlarmConfigTable
        resourceId={resource.id}
        initialConfigs={alarmConfigs}
        monitoringEnabled={monitoring}
        onAddCustomMetric={() => setShowCustomForm(true)}
        onRegisterAdd={(fn) => { addConfigRef.current = fn; }}
        onRegisterSetAllMonitoring={(fn) => { setAllMonitoringRef.current = fn; }}
      />

      {showCustomForm && (
        <CustomMetricForm
          resourceId={resource.id}
          open={showCustomForm}
          onClose={() => setShowCustomForm(false)}
          onAdd={handleAddCustomMetric}
        />
      )}
    </>
  );
}
