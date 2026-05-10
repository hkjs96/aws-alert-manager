import { type NextRequest, NextResponse } from "next/server";
import type { ConnectionTestResult } from "@/types/api";
import { mockDelay } from "@/lib/mock-delay";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  await mockDelay();

  const result: ConnectionTestResult = {
    status: "connected",
    message: `Successfully assumed role for account ${id}`,
    tested_at: new Date().toISOString(),
  };
  return NextResponse.json(result);
}
