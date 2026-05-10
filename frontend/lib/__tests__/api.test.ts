import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, buildFilterParams, buildQueryString } from "../api";
import { ApiError } from "@/types/api";

describe("apiFetch", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("성공 응답 시 JSON 데이터를 반환한다", async () => {
    const mockData = { id: 1, name: "test" };
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(mockData), { status: 200 }),
    );

    const result = await apiFetch<{ id: number; name: string }>("/api/test");
    expect(result).toEqual(mockData);
  });

  it("Content-Type: application/json 헤더를 설정한다", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    await apiFetch("/api/test");

    const [, options] = vi.mocked(globalThis.fetch).mock.calls[0];
    const headers = new Headers(options?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("API_BASE_URL을 path 앞에 붙인다", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    await apiFetch("/api/test");

    const [url] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(url).toBe("/api/test");
  });

  it("네트워크 에러 시 ApiError(0, NETWORK_ERROR)를 throw한다", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    try {
      await apiFetch("/api/test");
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as InstanceType<typeof ApiError>;
      expect(apiErr.status).toBe(0);
      expect(apiErr.code).toBe("NETWORK_ERROR");
      expect(apiErr.message).toBe("네트워크 연결을 확인해주세요");
    }
  });

  it("HTTP 에러 시 응답 body에서 code, message를 파싱하여 ApiError를 throw한다", async () => {
    const errorBody = { code: "NOT_FOUND", message: "리소스를 찾을 수 없습니다" };
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(errorBody), { status: 404 }),
    );

    try {
      await apiFetch("/api/test");
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as InstanceType<typeof ApiError>;
      expect(apiErr.status).toBe(404);
      expect(apiErr.code).toBe("NOT_FOUND");
      expect(apiErr.message).toBe("리소스를 찾을 수 없습니다");
    }
  });

  it("HTTP 에러 body 파싱 실패 시 기본 메시지를 사용한다", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response("not json", { status: 500 }),
    );

    await expect(apiFetch("/api/test")).rejects.toMatchObject({
      status: 500,
      code: "UNKNOWN",
      message: "요청 실패 (500)",
    });
  });

  it("추가 options를 fetch에 전달한다", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    await apiFetch("/api/test", { method: "POST", body: JSON.stringify({ a: 1 }) });

    const [, options] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(options?.method).toBe("POST");
  });
});

describe("buildFilterParams", () => {
  it("비어있지 않은 필터 값만 URLSearchParams에 포함한다", () => {
    const params = buildFilterParams({
      customer_id: "acme",
      account_id: "",
      service: undefined,
    });
    expect(params.get("customer_id")).toBe("acme");
    expect(params.has("account_id")).toBe(false);
    expect(params.has("service")).toBe(false);
  });

  it("모든 필터가 비어있으면 빈 URLSearchParams를 반환한다", () => {
    const params = buildFilterParams({});
    expect(params.toString()).toBe("");
  });

  it("모든 필터가 있으면 전부 포함한다", () => {
    const params = buildFilterParams({
      customer_id: "acme",
      account_id: "123",
      service: "EC2",
    });
    expect(params.get("customer_id")).toBe("acme");
    expect(params.get("account_id")).toBe("123");
    expect(params.get("service")).toBe("EC2");
  });
});

describe("buildQueryString", () => {
  it("undefined 값을 제외하고 쿼리 문자열을 생성한다", () => {
    const qs = buildQueryString({
      page: 1,
      page_size: 25,
      search: undefined,
      active: true,
    });
    expect(qs).toContain("page=1");
    expect(qs).toContain("page_size=25");
    expect(qs).toContain("active=true");
    expect(qs).not.toContain("search");
  });

  it("모든 값이 undefined이면 빈 문자열을 반환한다", () => {
    const qs = buildQueryString({ a: undefined, b: undefined });
    expect(qs).toBe("");
  });

  it("문자열, 숫자, boolean 값을 올바르게 변환한다", () => {
    const qs = buildQueryString({ name: "test", count: 42, flag: false });
    expect(qs).toContain("name=test");
    expect(qs).toContain("count=42");
    expect(qs).toContain("flag=false");
  });
});
