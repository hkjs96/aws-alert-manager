import { type NextRequest, NextResponse } from "next/server";
import { MOCK_ALARMS } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const state = searchParams.get("state");
  const search = searchParams.get("search")?.toLowerCase();

  let filtered = [...MOCK_ALARMS];
  if (state && state !== "ALL") {
    filtered = filtered.filter((a) => a.state === state);
  }
  if (search) {
    filtered = filtered.filter(
      (a) =>
        a.resource.toLowerCase().includes(search) ||
        a.metric.toLowerCase().includes(search),
    );
  }

  const header = "id,time,resource,arn,type,metric,state,value";
  const rows = filtered.map(
    (a) => `${a.id},${a.time},${a.resource},${a.arn},${a.type},${a.metric},${a.state},${a.value}`,
  );
  const csv = [header, ...rows].join("\n");

  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": `attachment; filename="alarms_${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}
