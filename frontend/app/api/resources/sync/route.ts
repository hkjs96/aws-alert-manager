import { NextResponse } from "next/server";
import type { SyncResult } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";
import { addResource, resourceExists } from "@/lib/mock-store";
import { createMockResource } from "@/lib/mock-data";

// Candidate resources that may be "discovered" on sync
const SYNC_CANDIDATES = [
  createMockResource({ id: "i-aabbccdd1122", name: "cache-server-prod-01", type: "EC2", account: "882311440092", region: "us-east-1", monitoring: false, alarms: { critical: 0, warning: 0 } }),
  createMockResource({ id: "db-NEWRDS99-RDS", name: "analytics-db-aurora", type: "RDS", account: "440911228833", region: "us-west-2", monitoring: false, alarms: { critical: 0, warning: 0 } }),
  createMockResource({ id: "arn:aws:lambda:u...reporter", name: "report-generator", type: "Lambda", account: "112233445566", region: "ap-northeast-2", monitoring: false, alarms: { critical: 0, warning: 0 } }),
] as const;

export async function POST() {
  await mockDelay();

  // Add candidates that don't exist yet
  const newResources = SYNC_CANDIDATES.filter((c) => !resourceExists(c.id));
  newResources.forEach((r) => addResource({ ...r }));

  // Simulate "updated" = resources that already existed (monitoring state refreshed)
  const result: SyncResult = {
    discovered: newResources.length,
    updated: newResources.length === 0 ? 0 : 1,
    removed: 0,
  };

  return NextResponse.json(result);
}
