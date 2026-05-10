import { type NextRequest, NextResponse } from "next/server";
import {
  addAlarm,
  addRecentAlarm,
  getResources,
  updateResourceMonitoring,
} from "@/lib/mock-store";
import type { Alarm, RecentAlarm, SeverityLevel } from "@/types";
import { mockDelay } from "@/lib/mock-delay";

interface CreateAlarmPayload {
  resource_id: string;
  track: 1 | 2;
  metrics: { metric_name: string; threshold: number; unit: string; direction: ">" | "<" }[];
}

export async function POST(request: NextRequest) {
  await mockDelay();
  const body = (await request.json()) as CreateAlarmPayload;

  const resource = getResources().find((r) => r.id === body.resource_id);
  if (!resource) {
    return NextResponse.json(
      { code: "NOT_FOUND", message: "Resource not found" },
      { status: 404 },
    );
  }

  // Track 2: enable monitoring on the resource
  if (body.track === 2) {
    updateResourceMonitoring(body.resource_id, true);
  }

  // Create alarm + recent alarm entries for each metric
  for (const m of body.metrics) {
    const alarmId = `alm-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date();
    const timeStr = `${now.getUTCHours().toString().padStart(2, "0")}:${now.getUTCMinutes().toString().padStart(2, "0")}:${now.getUTCSeconds().toString().padStart(2, "0")} UTC`;

    const alarm: Alarm = {
      id: alarmId,
      time: timeStr,
      resource: resource.name,
      arn: resource.id,
      type: resource.type,
      metric: m.metric_name,
      state: "OK",
      value: `— ${m.direction} ${m.threshold} ${m.unit}`,
    };
    addAlarm(alarm);

    const recent: RecentAlarm = {
      timestamp: now.toISOString(),
      resource_id: resource.id,
      resource_name: resource.name,
      resource_type: resource.type,
      metric: m.metric_name,
      severity: "SEV-3" as SeverityLevel,
      state_change: "OFF → OK",
      value: 0,
      threshold: m.threshold,
    };
    addRecentAlarm(recent);
  }

  return NextResponse.json({ success: true, count: body.metrics.length }, { status: 201 });
}
