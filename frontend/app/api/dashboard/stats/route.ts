import { NextResponse } from "next/server";
import { computeDashboardStats } from "@/lib/mock-store";
import { mockDelay } from "@/lib/mock-delay";

export async function GET() {
  await mockDelay();
  return NextResponse.json(computeDashboardStats());
}
