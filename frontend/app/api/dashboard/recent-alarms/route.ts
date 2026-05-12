import { type NextRequest, NextResponse } from "next/server";
import { getRecentAlarms, getAccounts } from "@/lib/mock-store";
import { paginate } from "@/lib/mock-data";
import { mockDelay } from "@/lib/mock-delay";
import { parsePaginationParams } from "@/lib/api-utils";

export async function GET(request: NextRequest) {
  await mockDelay();
  const { searchParams } = request.nextUrl;
  const { page, pageSize } = parsePaginationParams(searchParams);

  // ⚠️ Phase1: UX 필터 — 실제 접근 제어는 Phase2 BE에서 JWT claim으로 수행
  const customerId = searchParams.get("customer_id");
  const ownedCustomerIdsParam = searchParams.get("owned_customer_ids");
  const ownedCustomerIds = ownedCustomerIdsParam ? ownedCustomerIdsParam.split(",") : [];

  let filtered = [...getRecentAlarms()];

  if (customerId) {
    const accountIds = getAccounts()
      .filter((a) => a.customer_id === customerId)
      .map((a) => a.account_id);
    filtered = filtered.filter((a) => accountIds.includes(a.account));
  } else if (ownedCustomerIds.length > 0) {
    const ownedAccountIds = getAccounts()
      .filter((a) => ownedCustomerIds.includes(a.customer_id))
      .map((a) => a.account_id);
    filtered = filtered.filter((a) => ownedAccountIds.includes(a.account));
  }

  return NextResponse.json(paginate(filtered, page, pageSize));
}
