import type { AlarmStateFilter, FilterState } from "@/types/api";

export const ALLOWED_PAGE_SIZES = [25, 50, 100] as const;

const STRING_KEYS = [
  "customer_id",
  "account_id",
  "service",
  "sort",
  "resource_type",
  "search",
] as const;

/**
 * 필터 상태를 URL searchParams 문자열로 직렬화한다.
 * undefined/빈 문자열 값은 제외한다.
 */
export function serializeFilters(filters: FilterState): string {
  const params = new URLSearchParams();

  for (const key of STRING_KEYS) {
    const value = filters[key];
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }

  if (filters.order !== undefined) {
    params.set("order", filters.order);
  }
  if (filters.page !== undefined) {
    params.set("page", String(filters.page));
  }
  if (filters.page_size !== undefined) {
    params.set("page_size", String(filters.page_size));
  }
  if (filters.state !== undefined) {
    params.set("state", filters.state);
  }
  if (filters.monitoring !== undefined) {
    params.set("monitoring", String(filters.monitoring));
  }

  return params.toString();
}

const VALID_ALARM_STATES = new Set<string>(["ALL", "ALARM", "INSUFFICIENT", "OK", "OFF"]);

/**
 * URL searchParams를 필터 상태 객체로 파싱한다.
 * 잘못된 page_size는 25, 잘못된 page는 1로 기본값 처리한다.
 */
export function parseFilters(searchParams: URLSearchParams): FilterState {
  const result: FilterState = {};

  for (const key of STRING_KEYS) {
    const value = searchParams.get(key);
    if (value !== null && value !== "") {
      (result as Record<string, string>)[key] = value;
    }
  }

  const orderRaw = searchParams.get("order");
  if (orderRaw === "asc" || orderRaw === "desc") {
    result.order = orderRaw;
  }

  const pageRaw = searchParams.get("page");
  if (pageRaw !== null) {
    const parsed = Number(pageRaw);
    result.page = Number.isFinite(parsed) && parsed >= 1 ? parsed : 1;
  }

  const pageSizeRaw = searchParams.get("page_size");
  if (pageSizeRaw !== null) {
    const parsed = Number(pageSizeRaw);
    result.page_size = (ALLOWED_PAGE_SIZES as readonly number[]).includes(parsed)
      ? (parsed as 25 | 50 | 100)
      : 25;
  }

  const stateRaw = searchParams.get("state");
  if (stateRaw !== null && VALID_ALARM_STATES.has(stateRaw)) {
    result.state = stateRaw as AlarmStateFilter;
  }

  const monitoringRaw = searchParams.get("monitoring");
  if (monitoringRaw === "true") {
    result.monitoring = true;
  } else if (monitoringRaw === "false") {
    result.monitoring = false;
  }

  return result;
}

/**
 * 페이지네이션 파라미터를 검증하고 반환한다.
 * page는 1 이상으로 클램핑, page_size는 ALLOWED_PAGE_SIZES 중 하나여야 한다.
 */
export function buildPaginationParams(
  page: number,
  pageSize: number,
): { page: number; page_size: number } {
  return {
    page: Math.max(1, page),
    page_size: (ALLOWED_PAGE_SIZES as readonly number[]).includes(pageSize)
      ? pageSize
      : 25,
  };
}

/**
 * 정렬 파라미터를 검증하고 반환한다.
 * sort가 없으면 빈 객체, order는 "asc"/"desc" 중 하나여야 한다.
 */
export function buildSortParams(
  sort?: string,
  order?: string,
): { sort?: string; order?: "asc" | "desc" } {
  if (!sort) return {};
  return {
    sort,
    order: order === "desc" ? "desc" : "asc",
  };
}
