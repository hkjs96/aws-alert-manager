import { type NextRequest, NextResponse } from "next/server";
import { getResources, getAccounts } from "@/lib/mock-store";
import { paginate } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const customerId = searchParams.get("customer_id");
  const accountId = searchParams.get("account_id");
  const resourceType = searchParams.get("resource_type");
  const search = searchParams.get("search")?.toLowerCase();
  const page = Math.max(1, Number(searchParams.get("page") ?? "1"));
  const pageSize = Number(searchParams.get("page_size") ?? "25");
  const sort = searchParams.get("sort");
  const order = searchParams.get("order") ?? "asc";

  let filtered = [...getResources()];

  // Filter by customer_id → resolve to account IDs
  if (customerId) {
    const accountIds = getAccounts()
      .filter((a) => a.customer_id === customerId)
      .map((a) => a.account_id);
    filtered = filtered.filter((r) => accountIds.includes(r.account));
  }

  if (accountId) {
    filtered = filtered.filter((r) => r.account === accountId);
  }
  if (resourceType) {
    filtered = filtered.filter((r) => r.type === resourceType);
  }
  if (search) {
    filtered = filtered.filter(
      (r) => r.name.toLowerCase().includes(search) || r.id.toLowerCase().includes(search),
    );
  }

  // Sort
  if (sort) {
    filtered.sort((a, b) => {
      const aVal = String((a as unknown as Record<string, unknown>)[sort] ?? "");
      const bVal = String((b as unknown as Record<string, unknown>)[sort] ?? "");
      return order === "desc" ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
    });
  }

  return NextResponse.json(paginate(filtered, page, pageSize));
}
