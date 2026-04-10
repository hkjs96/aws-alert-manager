import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as fc from "fast-check";
import { apiFetch, buildFilterParams } from "../api";
import { ApiError } from "@/types/api";

describe("Property 1: API 에러 응답 구조화", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("HTTP 에러 상태 코드(400~599)에 대해 throw되는 에러가 status, code, message 필드를 포함한다", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        fc.string({ minLength: 1, maxLength: 20 }),
        fc.string({ minLength: 1, maxLength: 100 }),
        async (status, code, message) => {
          vi.mocked(globalThis.fetch).mockResolvedValue(
            new Response(JSON.stringify({ code, message }), { status }),
          );

          try {
            await apiFetch("/api/test");
            expect.unreachable("should have thrown");
          } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as InstanceType<typeof ApiError>;
            expect(apiErr.status).toBe(status);
            expect(typeof apiErr.code).toBe("string");
            expect(apiErr.code.length).toBeGreaterThan(0);
            expect(typeof apiErr.message).toBe("string");
            expect(apiErr.message.length).toBeGreaterThan(0);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it("HTTP 에러 body가 파싱 불가능해도 status, code, message 필드가 존재한다", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        async (status) => {
          vi.mocked(globalThis.fetch).mockResolvedValue(
            new Response("not json", { status }),
          );

          try {
            await apiFetch("/api/test");
            expect.unreachable("should have thrown");
          } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as InstanceType<typeof ApiError>;
            expect(apiErr.status).toBe(status);
            expect(apiErr.code).toBe("UNKNOWN");
            expect(apiErr.message).toContain(String(status));
          }
        },
      ),
      { numRuns: 30 },
    );
  });
});

describe("Property 2: 글로벌 필터 API 전파", () => {
  it("비어있지 않은 필터 값만 쿼리 파라미터로 포함한다", () => {
    fc.assert(
      fc.property(
        fc.record({
          customer_id: fc.oneof(fc.constant(undefined), fc.constant(""), fc.string({ minLength: 1, maxLength: 20 })),
          account_id: fc.oneof(fc.constant(undefined), fc.constant(""), fc.string({ minLength: 1, maxLength: 20 })),
          service: fc.oneof(fc.constant(undefined), fc.constant(""), fc.string({ minLength: 1, maxLength: 20 })),
        }),
        (filters) => {
          const params = buildFilterParams(filters);

          for (const [key, value] of Object.entries(filters)) {
            if (value !== undefined && value !== "") {
              expect(params.get(key)).toBe(value);
            } else {
              expect(params.has(key)).toBe(false);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
