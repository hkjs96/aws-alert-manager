import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { POST } from "../route";

/** sendBeacon이 보내는 형태의 요청을 만든다 */
function req(body: unknown, raw?: string) {
  return {
    json: async () => {
      if (raw !== undefined) return JSON.parse(raw);
      return body;
    },
  } as Parameters<typeof POST>[0];
}

let logged: string[];

beforeEach(() => {
  logged = [];
  vi.spyOn(console, "log").mockImplementation((line: string) => {
    logged.push(line);
  });
});
afterEach(() => vi.restoreAllMocks());

function parsed() {
  return logged.map((l) => JSON.parse(l.replace(/^PERF_METRIC /, "")));
}

describe("POST /api/vitals", () => {
  it("logs allowed vitals as compact structured lines", async () => {
    const res = await POST(
      req({
        page: "/dashboard",
        connection: "4g",
        metrics: [
          { name: "LCP", value: 1234.5678, rating: "good" },
          { name: "CLS", value: 0.05, rating: "good" },
        ],
      }),
    );
    expect(res.status).toBe(204);
    expect(parsed()).toEqual([
      { metric: "web_vital", vital: "LCP", page: "/dashboard", value: 1234.568, rating: "good", connection: "4g" },
      { metric: "web_vital", vital: "CLS", page: "/dashboard", value: 0.05, rating: "good", connection: "4g" },
    ]);
    // Insights 정규식이 읽는 형태여야 한다 (공백 없는 JSON, 고정 마커)
    expect(logged[0]).toMatch(/^PERF_METRIC \{"metric":"web_vital"/);
  });

  it("collapses resource ids so the page axis stays bounded", async () => {
    await POST(
      req({
        page: "/resources/aXJuOmF3czpl?tab=alarms",
        metrics: [{ name: "LCP", value: 900, rating: "good" }],
      }),
    );
    expect(parsed()[0].page).toBe("/resources/{id}");
  });

  it("drops unknown metric names and out-of-range values", async () => {
    await POST(
      req({
        page: "/alarms",
        metrics: [
          { name: "EVIL", value: 1, rating: "x" },
          { name: "LCP", value: -5, rating: "good" },
          { name: "LCP", value: 10_000_000, rating: "good" },
          { name: "LCP", value: Number.NaN, rating: "good" },
          { name: "TTFB", value: 120, rating: "good" },
        ],
      }),
    );
    expect(parsed().map((r) => r.vital)).toEqual(["TTFB"]);
  });

  it("does not trust a malformed page value", async () => {
    await POST(req({ page: "javascript:alert(1)", metrics: [{ name: "TTFB", value: 1, rating: "" }] }));
    expect(parsed()[0].page).toBe("/unknown");
  });

  it("caps the number of metrics per beacon", async () => {
    const metrics = Array.from({ length: 50 }, () => ({ name: "TTFB", value: 1, rating: "good" }));
    await POST(req({ page: "/", metrics }));
    expect(logged.length).toBeLessThanOrEqual(12);
  });

  it("returns 204 without logging on invalid JSON", async () => {
    const res = await POST({
      json: async () => {
        throw new SyntaxError("bad");
      },
    } as Parameters<typeof POST>[0]);
    expect(res.status).toBe(204);
    expect(logged).toEqual([]);
  });

  it("ignores a non-array metrics field", async () => {
    const res = await POST(req({ page: "/", metrics: "nope" }));
    expect(res.status).toBe(204);
    expect(logged).toEqual([]);
  });
});
