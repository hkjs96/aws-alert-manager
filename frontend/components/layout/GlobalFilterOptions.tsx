import { fetchAccounts, fetchCustomers } from "@/lib/server/data";
import { GlobalFilterBar } from "./GlobalFilterBar";
import type { Account, Customer } from "@/types";

/**
 * 글로벌 필터 옵션 (서버 컴포넌트, Suspense 슬롯).
 * 예전에는 GlobalFilterBar가 마운트마다 /api/customers·/api/accounts를 클라이언트에서
 * 다시 불렀다 — 서버 컴포넌트가 이미 페이지에 내려준 데이터의 중복 요청.
 * 서버에서 한 번 읽어 props로 넘기며, cache() 덕에 페이지 fetch와 합산 1회다.
 */
export async function GlobalFilterOptions() {
  let customers: Customer[] = [];
  let accounts: Account[] = [];
  try {
    [customers, accounts] = await Promise.all([fetchCustomers(), fetchAccounts()]);
  } catch (error) {
    console.error("[GlobalFilterOptions] Failed to fetch filter options:", error);
  }
  return <GlobalFilterBar customers={customers} accounts={accounts} />;
}
