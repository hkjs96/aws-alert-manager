import { type NextRequest, NextResponse } from "next/server";
import { MOCK_RESOURCES } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const resourceType = searchParams.get("resource_type");
  const search = searchParams.get("search")?.toLowerCase();

  let filtered = [...MOCK_RESOURCES];
  if (resourceType) {
    filtered = filtered.filter((r) => r.type === resourceType);
  }
  if (search) {
    filtered = filtered.filter(
      (r) => r.name.toLowerCase().includes(search) || r.id.toLowerCase().includes(search),
    );
  }

  const header = "id,name,type,account,region,monitoring,critical_alarms,warning_alarms";
  const rows = filtered.map(
    (r) => `${r.id},${r.name},${r.type},${r.account},${r.region},${r.monitoring},${r.alarms.critical},${r.alarms.warning}`,
  );
  const csv = [header, ...rows].join("\n");

  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": `attachment; filename="resources_${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}
