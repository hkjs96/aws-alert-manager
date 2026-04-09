import { type NextRequest, NextResponse } from "next/server";
import { getAlarms } from "@/lib/mock-store";
import { paginate } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const state = searchParams.get("state");
  const search = searchParams.get("search")?.toLowerCase();
  const page = Math.max(1, Number(searchParams.get("page") ?? "1"));
  const pageSize = Number(searchParams.get("page_size") ?? "25");

  let filtered = [...getAlarms()];

  if (state && state !== "ALL") {
    filtered = filtered.filter((a) => a.state === state);
  }
  if (search) {
    filtered = filtered.filter(
      (a) =>
        a.resource.toLowerCase().includes(search) ||
        a.metric.toLowerCase().includes(search) ||
        a.type.toLowerCase().includes(search),
    );
  }

  return NextResponse.json(paginate(filtered, page, pageSize));
}
