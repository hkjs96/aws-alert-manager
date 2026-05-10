import { type NextRequest, NextResponse } from "next/server";
import { getResources } from "@/lib/mock-store";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await mockDelay();
  const { id } = await params;
  const resource = getResources().find((r) => r.id === id);
  if (!resource) {
    return NextResponse.json({ code: "NOT_FOUND", message: "Resource not found" }, { status: 404 });
  }
  return NextResponse.json(resource);
}
