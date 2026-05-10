import { type NextRequest, NextResponse } from "next/server";
import { getMockThresholdOverrides } from "@/lib/mock-data";
import type { ThresholdOverride } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ type: string }> },
) {
  await mockDelay();
  const { type } = await params;
  return NextResponse.json(getMockThresholdOverrides(type));
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ type: string }> },
) {
  await mockDelay();
  const { type } = await params;
  const body = (await request.json()) as ThresholdOverride[];

  // Simulate save — return the submitted overrides as-is
  const current = getMockThresholdOverrides(type);
  const merged = current.map((t) => {
    const update = body.find((u) => u.metric_key === t.metric_key);
    if (update) {
      return { ...t, customer_override: update.customer_override };
    }
    return t;
  });

  return NextResponse.json(merged);
}
