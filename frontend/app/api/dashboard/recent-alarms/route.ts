import { type NextRequest, NextResponse } from "next/server";
import { getRecentAlarms } from "@/lib/mock-store";
import { paginate } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const page = Math.max(1, Number(searchParams.get("page") ?? "1"));
  const pageSize = Number(searchParams.get("page_size") ?? "25");

  return NextResponse.json(paginate(getRecentAlarms(), page, pageSize));
}
