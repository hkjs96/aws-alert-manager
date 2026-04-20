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

  return (
    <>
      <ResourceHeader resource={resource} onMonitoringChange={handleMonitoringChange} />

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
