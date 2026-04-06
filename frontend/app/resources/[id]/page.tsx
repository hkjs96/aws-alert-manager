"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { AlarmConfig } from "@/types";
import { MonitoringToggle } from "@/components/shared/MonitoringToggle";
import { AlarmConfigTable } from "@/components/resources/AlarmConfigTable";
import { CustomMetricForm } from "@/components/resources/CustomMetricForm";

// TODO: Replace with API call based on resource type
const MOCK_EC2_ALARMS: AlarmConfig[] = [
  { metric_key: "CPU", metric_name: "CPUUtilization", namespace: "AWS/EC2", threshold: 80, unit: "%", direction: ">", severity: "SEV-3", source: "System", state: "OK", current_value: 23.4, monitoring: true },
  { metric_key: "Memory", metric_name: "mem_used_percent", namespace: "CWAgent", threshold: 80, unit: "%", direction: ">", severity: "SEV-3", source: "Customer", state: "OK", current_value: 45.2, monitoring: true },
  { metric_key: "Disk", metric_name: "disk_used_percent", namespace: "CWAgent", threshold: 80, unit: "%", direction: ">", severity: "SEV-3", source: "Custom", state: "ALARM", current_value: 82.1, monitoring: true, mount_path: "/" },
  { metric_key: "Disk", metric_name: "disk_used_percent", namespace: "CWAgent", threshold: 80, unit: "%", direction: ">", severity: "SEV-3", source: "System", state: "OK", current_value: 55.3, monitoring: false, mount_path: "/data" },
  { metric_key: "StatusCheckFailed", metric_name: "StatusCheckFailed", namespace: "AWS/EC2", threshold: 0, unit: "", direction: ">", severity: "SEV-1", source: "System", state: "OK", current_value: 0, monitoring: true },
];

export default function ResourceDetailPage() {
  const params = useParams();
  const resourceId = decodeURIComponent(params.id as string);

  const [monitoring, setMonitoring] = useState(true);
  const [alarms, setAlarms] = useState<AlarmConfig[]>(MOCK_EC2_ALARMS);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [dirty, setDirty] = useState(false);

  const handleAlarmsChange = (updated: AlarmConfig[]) => {
    setAlarms(updated);
    setDirty(true);
  };

  const handleSave = () => {
    console.log("Save alarms", alarms);
    setDirty(false);
  };

  const handleReset = () => {
    setAlarms(MOCK_EC2_ALARMS);
    setDirty(false);
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-slate-400">
        <Link href="/resources" className="hover:text-accent">Resources</Link>
        <span className="mx-2">›</span>
        <span className="text-slate-600">EC2</span>
        <span className="mx-2">›</span>
        <span className="text-slate-800">web-server-prod-01</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">web-server-prod-01</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-slate-500">{resourceId}</span>
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium">EC2</span>
            <span className="text-xs text-slate-400">882311440092</span>
            <span className="text-xs text-slate-400">us-east-1</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2">
            <span className="text-sm text-slate-600">모니터링</span>
            <MonitoringToggle size="lg" enabled={monitoring} onChange={setMonitoring} />
            <span className={`text-sm font-medium ${monitoring ? "text-green-600" : "text-slate-400"}`}>
              {monitoring ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </div>

      {/* Alarm Configuration */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium text-slate-700">알람 설정</h2>
          <button
            onClick={() => setShowCustomForm(true)}
            className="flex items-center gap-1 rounded-md border border-accent px-3 py-1.5 text-sm font-medium text-accent hover:bg-blue-50"
          >
            + 커스텀 메트릭 추가
          </button>
        </div>

        <AlarmConfigTable alarms={alarms} onChange={handleAlarmsChange} />

        {showCustomForm && (
          <div className="mt-4">
            <CustomMetricForm
              onAdd={(metric) => {
                const newAlarm: AlarmConfig = {
                  metric_key: metric.name,
                  metric_name: metric.name,
                  namespace: "Custom",
                  threshold: metric.threshold,
                  unit: metric.unit,
                  direction: metric.direction,
                  severity: "SEV-5",
                  source: "Custom",
                  state: "INSUFFICIENT_DATA",
                  current_value: null,
                  monitoring: true,
                };
                setAlarms([...alarms, newAlarm]);
                setShowCustomForm(false);
                setDirty(true);
              }}
              onCancel={() => setShowCustomForm(false)}
            />
          </div>
        )}
      </div>

      {/* Action Bar */}
      <div className="sticky bottom-0 flex items-center justify-between border-t border-slate-200 bg-white py-4">
        <div>
          {dirty && (
            <span className="flex items-center gap-1.5 text-sm text-amber-600">
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              미저장 변경사항
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleReset}
            className="rounded-md border border-slate-200 px-4 py-2 text-sm hover:bg-slate-50"
          >
            기본값으로 초기화
          </button>
          <button
            onClick={handleSave}
            disabled={!dirty}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            변경사항 저장
          </button>
        </div>
      </div>
    </div>
  );
}
