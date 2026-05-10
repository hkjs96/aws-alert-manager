import { type NextRequest, NextResponse } from "next/server";
import { getResources, getAccounts } from "@/lib/mock-store";
import { paginate } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";
import { parsePaginationParams, parseSearchParam, parseSortParams } from "@/lib/api-utils";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const customerId = searchParams.get("customer_id");
  const accountId = searchParams.get("account_id");
  const resourceType = searchParams.get("resource_type");
  const search = parseSearchParam(searchParams);
  const { page, pageSize } = parsePaginationParams(searchParams);
  const { sort, order } = parseSortParams(searchParams);

  // ⚠️ Phase1: UX 필터 — 실제 접근 제어는 Phase2 BE에서 JWT claim으로 수행
  const ownedCustomerIdsParam = searchParams.get("owned_customer_ids");
  const ownedCustomerIds = ownedCustomerIdsParam ? ownedCustomerIdsParam.split(",") : [];

  let filtered = [...getResources()];

  // Filter by customer_id (explicit) or owned_customer_ids (scope filter)
  if (customerId) {
    const accountIds = getAccounts()
      .filter((a) => a.customer_id === customerId)
      .map((a) => a.account_id);
    filtered = filtered.filter((r) => accountIds.includes(r.account));
  } else if (ownedCustomerIds.length > 0) {
    const ownedAccountIds = getAccounts()
      .filter((a) => ownedCustomerIds.includes(a.customer_id))
      .map((a) => a.account_id);
    filtered = filtered.filter((r) => ownedAccountIds.includes(r.account));
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
