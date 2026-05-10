/**
 * API 라우트 공통 유틸리티 — 쿼리 파라미터 파싱 헬퍼
 *
 * 5개 이상의 API 라우트에서 반복되는 pagination / filter 파싱 로직을 단일 모듈로 통합.
 */

export interface PaginationParams {
  page: number;
  pageSize: number;
}

export interface SortParams {
  sort: string | null;
  order: "asc" | "desc";
}

/**
 * URLSearchParams에서 pagination 파라미터를 파싱한다.
 * - page: 1 이상의 정수. 기본값 1.
 * - page_size: 정수. 기본값 25.
 */
export function parsePaginationParams(searchParams: URLSearchParams): PaginationParams {
  return {
    page: Math.max(1, Number(searchParams.get("page") ?? "1")),
    pageSize: Number(searchParams.get("page_size") ?? "25"),
  };
}

/**
 * URLSearchParams에서 search 파라미터를 소문자로 파싱한다.
 * 값이 없으면 null 반환.
 */
export function parseSearchParam(searchParams: URLSearchParams): string | null {
  return searchParams.get("search")?.toLowerCase() ?? null;
}

/**
 * URLSearchParams에서 sort / order 파라미터를 파싱한다.
 * - sort: 정렬 기준 필드명. 없으면 null.
 * - order: "asc" | "desc". 기본값 "asc".
 */
export function parseSortParams(searchParams: URLSearchParams): SortParams {
  const order = searchParams.get("order");
  return {
    sort: searchParams.get("sort"),
    order: order === "desc" ? "desc" : "asc",
  };
}
