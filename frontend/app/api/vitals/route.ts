import { type NextRequest, NextResponse } from "next/server";

/**
 * Web Vitals 수집 엔드포인트 — 브라우저가 보낸 측정을 구조화 로그로 남긴다.
 *
 * 저장소를 두지 않는 이유: 이 값은 "지금 느린가"를 보는 집계용이지 레코드가 아니다.
 * Amplify SSR의 stdout은 CloudWatch Logs로 가므로 Logs Insights로 p50/p95를 뽑을 수 있고,
 * DynamoDB 테이블이나 커스텀 메트릭($0.30/메트릭/월)을 새로 만들 필요가 없다.
 * 쿼리: docs/OBSERVABILITY.md
 *
 * 이 경로는 정적 세그먼트라 catch-all 프록시(/api/[...path])보다 우선 매칭된다 —
 * 즉 백엔드로 넘어가지 않는다.
 */

/** Logs Insights가 잡는 고정 마커 (backend/common/perf_log.py와 동일 규약) */
const PERF_MARKER = "PERF_METRIC";

/** 브라우저가 보내는 값은 신뢰할 수 없다 — 알려진 지표만, 상식 범위 안에서 받는다. */
const ALLOWED_METRICS = new Set([
  "LCP", "CLS", "INP", "FCP", "TTFB", "FID",
  "Next.js-hydration", "Next.js-route-change-to-render", "Next.js-render",
]);
const MAX_METRICS = 12;
const MAX_VALUE = 600_000; // 10분. 이보다 큰 값은 측정 오류로 본다.

interface VitalPayload {
  page?: unknown;
  metrics?: unknown;
  connection?: unknown;
}

function sanitizePage(page: unknown): string {
  if (typeof page !== "string" || !page.startsWith("/")) return "/unknown";
  // 경로에 리소스 ID가 들어가면 집계 축이 무한히 늘어난다 — 동적 세그먼트를 정규화한다.
  return page
    .slice(0, 200)
    .replace(/\/resources\/[^/]+/, "/resources/{id}")
    .replace(/\?.*$/, "");
}

export async function POST(request: NextRequest) {
  let body: VitalPayload;
  try {
    body = await request.json();
  } catch {
    return new NextResponse(null, { status: 204 });
  }

  const metrics = Array.isArray(body.metrics) ? body.metrics.slice(0, MAX_METRICS) : [];
  const page = sanitizePage(body.page);
  const connection =
    typeof body.connection === "string" ? body.connection.slice(0, 20) : "";

  for (const raw of metrics) {
    if (typeof raw !== "object" || raw === null) continue;
    const { name, value, rating } = raw as Record<string, unknown>;
    if (typeof name !== "string" || !ALLOWED_METRICS.has(name)) continue;
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > MAX_VALUE) {
      continue;
    }
    console.log(
      `${PERF_MARKER} ${JSON.stringify({
        metric: "web_vital",
        vital: name,
        page,
        value: Math.round(value * 1000) / 1000,
        rating: typeof rating === "string" ? rating.slice(0, 20) : "",
        connection,
      })}`,
    );
  }

  // 브라우저는 응답을 쓰지 않는다 (sendBeacon). 본문 없이 즉시 닫는다.
  return new NextResponse(null, { status: 204 });
}
