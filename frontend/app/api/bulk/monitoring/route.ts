import { type NextRequest, NextResponse } from "next/server";
import type { BulkMonitoringRequest, BulkOperationResponse } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function POST(request: NextRequest) {
  await mockDelay();
  const body = (await request.json()) as BulkMonitoringRequest;

  const result: BulkOperationResponse = {
    job_id: `job-bulk-${Date.now()}`,
    total: body.resource_ids.length,
    status: "pending",
  };
  return NextResponse.json(result);
}
