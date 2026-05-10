import { NextResponse } from "next/server";
import { computeAlarmSummary } from "@/lib/mock-store";
import { mockDelay } from "@/lib/mock-delay";

export async function GET() {
  await mockDelay();
  return NextResponse.json(computeAlarmSummary());
}
