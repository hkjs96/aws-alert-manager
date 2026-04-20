import { type NextRequest, NextResponse } from "next/server";
import { getResources, updateResourceMonitoring } from "@/lib/mock-store";
import type { JobStatus } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await mockDelay();
  const { id } = await params;
  const resource = getResources().find((r) => r.id === id);
  if (!resource) {
    return NextResponse.json({ code: "NOT_FOUND", message: "Resource not found" }, { status: 404 });
  }

  const body = (await request.json()) as { monitoring: boolean };
  updateResourceMonitoring(id, body.monitoring);

  const result: JobStatus = {
    job_id: `job-${Date.now()}`,
    status: "completed",
    total_count: 1,
    completed_count: 1,
    failed_count: 0,
    results: [{ resource_id: id, status: "success" }],
  };
  return NextResponse.json(result);
}
