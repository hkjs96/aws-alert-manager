import { type NextRequest, NextResponse } from "next/server";
import { getMockEvents } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await mockDelay();
  const { id } = await params;
  return NextResponse.json(getMockEvents(id));
}
