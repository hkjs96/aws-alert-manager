import { type NextRequest, NextResponse } from "next/server";
import { getMockAlarmConfigs, MOCK_RESOURCES } from "@/lib/mock-data";
import type { SaveAlarmConfigRequest } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await mockDelay();
  const { id } = await params;
  const configs = getMockAlarmConfigs(id);
  return NextResponse.json(configs);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const resource = MOCK_RESOURCES.find((r) => r.id === id);
  if (!resource) {
    return NextResponse.json({ code: "NOT_FOUND", message: "Resource not found" }, { status: 404 });
  }

  const body = (await request.json()) as SaveAlarmConfigRequest;
  await mockDelay();
  // Simulate save — return updated configs
  const configs = getMockAlarmConfigs(id).map((c) => {
    const update = body.configs.find((u) => u.metric_key === c.metric_key);
    if (update) {
      return { ...c, threshold: update.threshold, monitoring: update.monitoring };
    }
    return c;
  });
  return NextResponse.json(configs);
}
