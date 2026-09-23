/**
 * 페이지 목록 API를 끝까지 모은다.
 *
 * 리소스·알람 목록 화면은 필터(고객사·계정·타입)를 브라우저에서 걸기 때문에 서버에서 **전체**를 받아야 한다.
 * 2026-09-23까지 서버 쪽 fetch는 `page_size=100`으로 첫 페이지만 받았다 — 첫 고객사 계정이 붙어 리소스가
 * 42개에서 266개가 되자 화면에 100개만 보였고, DynamoDB 스캔 순서라 어떤 100개가 보일지도 매번 달랐다.
 */

export interface Page<T> {
  items: T[];
  total: number;
}

/** 한 화면에 모을 최대 페이지 수. 넘으면 잘라 내고 경고한다 — 무한히 부르지 않는다. */
export const MAX_PAGES = 50;

export async function collectAllPages<T>(
  fetchPage: (page: number) => Promise<Page<T>>,
  pageSize: number,
  keyOf: (item: T) => string,
  maxPages: number = MAX_PAGES,
): Promise<T[]> {
  const first = await fetchPage(1);
  const wanted = Math.ceil(first.total / pageSize);
  const pages = Math.min(wanted, maxPages);
  if (wanted > maxPages) {
    console.warn(`collectAllPages: ${first.total} items exceed ${maxPages} pages of ${pageSize}; truncated`);
  }
  const rest = pages > 1
    ? await Promise.all(Array.from({ length: pages - 1 }, (_, i) => fetchPage(i + 2)))
    : [];

  // 페이지마다 서버가 표를 새로 훑는다 — 그 사이 행이 바뀌면 같은 항목이 두 페이지에 걸칠 수 있어 키로 접는다.
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of [first, ...rest].flatMap((p) => p.items)) {
    const key = keyOf(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}
