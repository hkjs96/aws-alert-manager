import { describe, it, expect } from "vitest";
import {
  serializeFilters,
  parseFilters,
  ALLOWED_PAGE_SIZES,
  buildPaginationParams,
  buildSortParams,
} from "../filterParams";
import type { FilterState } from "@/types/api";

describe("serializeFilters → parseFilters 라운드트립", () => {
  it("모든 필터 값이 직렬화 후 파싱하면 원래 값과 동일하다", () => {
    const original: FilterState = {
      customer_id: "acme",
      account_id: "123",
      service: "EC2",
      page: 2,
      page_size: 50,
      sort: "name",
      order: "desc",
      resource_type: "AWS::EC2::Instance",
      search: "web-server",
      state: "ALARM",
      monitoring: true,
    };
    const serialized = serializeFilters(original);
    const parsed = parseFilters(new URLSearchParams(serialized));
    expect(parsed).toEqual(original);
  });

  it("monitoring=false도 라운드트립이 유지된다", () => {
    const original: FilterState = {
      page: 1,
      page_size: 25,
      monitoring: false,
    };
    const serialized = serializeFilters(original);
    const parsed = parseFilters(new URLSearchParams(serialized));
    expect(parsed).toEqual(original);
  });
});

describe("빈 필터 직렬화", () => {
  it("모든 값이 undefined이면 빈 문자열을 반환한다", () => {
    const result = serializeFilters({});
    expect(result).toBe("");
  });

  it("빈 문자열 값은 제외한다", () => {
    const result = serializeFilters({ customer_id: "", search: "" });
    expect(result).toBe("");
  });
});

describe("잘못된 page_size 기본값 처리", () => {
  it("허용되지 않은 page_size는 25로 기본값 처리된다", () => {
    const params = new URLSearchParams("page_size=30");
    const parsed = parseFilters(params);
    expect(parsed.page_size).toBe(25);
  });

  it("page_size가 없으면 기본값 없이 undefined이다", () => {
    const params = new URLSearchParams("");
    const parsed = parseFilters(params);
    expect(parsed.page_size).toBeUndefined();
  });
});

describe("잘못된 page 기본값 처리", () => {
  it("page가 0이면 1로 기본값 처리된다", () => {
    const params = new URLSearchParams("page=0");
    const parsed = parseFilters(params);
    expect(parsed.page).toBe(1);
  });

  it("page가 음수이면 1로 기본값 처리된다", () => {
    const params = new URLSearchParams("page=-5");
    const parsed = parseFilters(params);
    expect(parsed.page).toBe(1);
  });

  it("page가 숫자가 아니면 1로 기본값 처리된다", () => {
    const params = new URLSearchParams("page=abc");
    const parsed = parseFilters(params);
    expect(parsed.page).toBe(1);
  });
});

describe("buildPaginationParams 유효성 검증", () => {
  it("유효한 page와 page_size를 그대로 반환한다", () => {
    expect(buildPaginationParams(3, 50)).toEqual({ page: 3, page_size: 50 });
  });

  it("page가 0 이하이면 1로 클램핑한다", () => {
    expect(buildPaginationParams(0, 25)).toEqual({ page: 1, page_size: 25 });
    expect(buildPaginationParams(-3, 25)).toEqual({ page: 1, page_size: 25 });
  });

  it("허용되지 않은 page_size는 25로 기본값 처리한다", () => {
    expect(buildPaginationParams(1, 10)).toEqual({ page: 1, page_size: 25 });
    expect(buildPaginationParams(1, 99)).toEqual({ page: 1, page_size: 25 });
  });
});

describe("buildSortParams 유효성 검증", () => {
  it("유효한 sort와 order를 그대로 반환한다", () => {
    expect(buildSortParams("name", "desc")).toEqual({ sort: "name", order: "desc" });
  });

  it("order가 없으면 asc로 기본값 처리한다", () => {
    expect(buildSortParams("name")).toEqual({ sort: "name", order: "asc" });
  });

  it("order가 유효하지 않으면 asc로 기본값 처리한다", () => {
    expect(buildSortParams("name", "invalid")).toEqual({ sort: "name", order: "asc" });
  });

  it("sort가 없으면 빈 객체를 반환한다", () => {
    expect(buildSortParams()).toEqual({});
    expect(buildSortParams(undefined, "desc")).toEqual({});
  });
});

describe("ALLOWED_PAGE_SIZES 상수", () => {
  it("[25, 50, 100]이다", () => {
    expect(ALLOWED_PAGE_SIZES).toEqual([25, 50, 100]);
  });
});
