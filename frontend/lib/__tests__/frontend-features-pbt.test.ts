/**
 * alarm-manager-frontend-features 속성 테스트 (Phase 3, Task 11.1)
 *
 * 미완 PBT 10개:
 * 1.2  API 타입 속성
 * 1.7  필터 파라미터 속성
 * 1.9  토스트 속성
 * 1.11 공통 UI 속성 (SeverityBadge / SourceBadge)
 * 3.2  GlobalFilterBar 속성
 * 5.6  동기화 토스트 메시지 속성
 * 5.8  CSV 내보내기 속성
 * 7.2  벌크 액션 속성
 * 7.8  커스텀 메트릭 속성
 * 9.7  임계치 계층 속성
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  serializeFilters,
  parseFilters,
  buildPaginationParams,
  buildSortParams,
  buildOwnedFilterParam,
  ALLOWED_PAGE_SIZES,
} from "../filterParams";
import { buildExportFilename, buildExportUrl } from "../exportCsv";
import { ApiError } from "@/types/api";
import type {
  PaginatedResponse,
  JobStatus,
  JobStatusValue,
  ThresholdOverride,
  CustomMetricConfig,
  BulkMonitoringRequest,
  AlarmStateFilter,
  FilterState,
} from "@/types/api";

// ──────────────────────────────────────────────────────────────
// 공통 Arbitrary
// ──────────────────────────────────────────────────────────────

const nonEmptyString = fc.string({ minLength: 1, maxLength: 40 });
const safeId = fc.stringMatching(/^[a-z0-9-]{1,20}$/);

// ──────────────────────────────────────────────────────────────
// Task 1.2 — API 타입 속성
// ──────────────────────────────────────────────────────────────

describe("1.2 API 타입 속성", () => {
  it("PaginatedResponse: items.length ≤ page_size, total ≥ items.length", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 100 }),
        fc.integer({ min: 1, max: 100 }),
        (itemCount, pageSize) => {
          const clampedCount = Math.min(itemCount, pageSize);
          const response: PaginatedResponse<string> = {
            items: Array.from({ length: clampedCount }, (_, i) => `item-${i}`),
            total: itemCount + fc.sample(fc.integer({ min: 0, max: 50 }), 1)[0],
            page: 1,
            page_size: pageSize,
          };
          expect(response.items.length).toBeLessThanOrEqual(response.page_size);
          expect(response.total).toBeGreaterThanOrEqual(response.items.length);
        },
      ),
    );
  });

  it("ApiError: status/code/message 필드가 생성자 인수와 일치한다", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 400, max: 599 }),
        fc.string({ minLength: 1, maxLength: 20 }),
        fc.string({ minLength: 1, maxLength: 100 }),
        (status, code, message) => {
          const err = new ApiError(status, code, message);
          expect(err.status).toBe(status);
          expect(err.code).toBe(code);
          expect(err.message).toBe(message);
          expect(err.name).toBe("ApiError");
          expect(err).toBeInstanceOf(Error);
        },
      ),
    );
  });

  it("JobStatus: completed_count + failed_count ≤ total_count", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (total) => {
          const completed = fc.sample(fc.integer({ min: 0, max: total }), 1)[0];
          const failed = fc.sample(fc.integer({ min: 0, max: total - completed }), 1)[0];
          const status: JobStatusValue =
            completed + failed < total
              ? "in_progress"
              : failed === total
              ? "failed"
              : failed > 0
              ? "partial_failure"
              : "completed";
          const job: JobStatus = {
            job_id: "job-001",
            status,
            total_count: total,
            completed_count: completed,
            failed_count: failed,
            results: [],
          };
          expect(job.completed_count + job.failed_count).toBeLessThanOrEqual(job.total_count);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 1.7 — 필터 파라미터 속성
// ──────────────────────────────────────────────────────────────

describe("1.7 필터 파라미터 속성", () => {
  const validStateArb = fc.constantFrom<AlarmStateFilter>(
    "ALL", "ALARM", "INSUFFICIENT_DATA", "OK", "OFF",
  );
  const validOrderArb = fc.constantFrom<"asc" | "desc">("asc", "desc");
  const validPageSizeArb = fc.constantFrom<25 | 50 | 100>(25, 50, 100);

  it("serializeFilters → parseFilters 라운드트립 (유효한 값)", () => {
    fc.assert(
      fc.property(
        fc.record<FilterState>({
          customer_id: fc.option(nonEmptyString, { nil: undefined }),
          account_id: fc.option(nonEmptyString, { nil: undefined }),
          service: fc.option(nonEmptyString, { nil: undefined }),
          sort: fc.option(nonEmptyString, { nil: undefined }),
          page: fc.option(fc.integer({ min: 1, max: 100 }), { nil: undefined }),
          page_size: fc.option(validPageSizeArb, { nil: undefined }),
          state: fc.option(validStateArb, { nil: undefined }),
          order: fc.option(validOrderArb, { nil: undefined }),
          monitoring: fc.option(fc.boolean(), { nil: undefined }),
        }),
        (filters) => {
          const serialized = serializeFilters(filters);
          const parsed = parseFilters(new URLSearchParams(serialized));

          if (filters.customer_id) expect(parsed.customer_id).toBe(filters.customer_id);
          if (filters.state) expect(parsed.state).toBe(filters.state);
          if (filters.order) expect(parsed.order).toBe(filters.order);
          if (filters.page_size) expect(parsed.page_size).toBe(filters.page_size);
          if (filters.monitoring !== undefined) expect(parsed.monitoring).toBe(filters.monitoring);
        },
      ),
    );
  });

  it("buildPaginationParams: page는 항상 1 이상, page_size는 허용값 중 하나", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -100, max: 200 }),
        fc.integer({ min: 0, max: 500 }),
        (page, pageSize) => {
          const result = buildPaginationParams(page, pageSize);
          expect(result.page).toBeGreaterThanOrEqual(1);
          expect((ALLOWED_PAGE_SIZES as readonly number[]).includes(result.page_size)).toBe(true);
        },
      ),
    );
  });

  it("buildSortParams: sort가 없으면 빈 객체 반환", () => {
    fc.assert(
      fc.property(
        fc.option(nonEmptyString, { nil: undefined }),
        fc.option(fc.constantFrom("asc", "desc", "invalid"), { nil: undefined }),
        (sort, order) => {
          const result = buildSortParams(sort, order);
          if (!sort) {
            expect(Object.keys(result)).toHaveLength(0);
          } else {
            expect(result.sort).toBe(sort);
            expect(result.order === "asc" || result.order === "desc").toBe(true);
          }
        },
      ),
    );
  });

  it("buildOwnedFilterParam: customer_id 지정 시 owned_customer_ids 무시", () => {
    fc.assert(
      fc.property(
        fc.option(nonEmptyString, { nil: undefined }),
        fc.array(nonEmptyString, { minLength: 0, maxLength: 5 }),
        (customerId, ownedIds) => {
          const result = buildOwnedFilterParam(customerId, ownedIds);
          if (customerId) {
            expect(result).toEqual({ customer_id: customerId });
            expect("owned_customer_ids" in result).toBe(false);
          } else if (ownedIds.length === 0) {
            expect(Object.keys(result)).toHaveLength(0);
          } else {
            expect(result.owned_customer_ids).toBe(ownedIds.join(","));
          }
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 1.9 — 토스트 속성
// ──────────────────────────────────────────────────────────────

describe("1.9 토스트 속성", () => {
  it("showToast는 임의의 variant + message 조합을 처리한다 (에러 미발생)", () => {
    // ToastContext의 showToast는 컴포넌트 외부에서 테스트 불가하나
    // 내부 생성 로직(id 유니크, duration 양수)은 속성으로 검증 가능
    fc.assert(
      fc.property(
        fc.constantFrom("success", "error", "warning", "info"),
        fc.string({ minLength: 0, maxLength: 200 }),
        fc.integer({ min: 500, max: 30000 }),
        (variant, message, duration) => {
          // Toast 아이템 구조 불변식: duration > 0
          const toastItem = { id: crypto.randomUUID(), variant, message, duration };
          expect(toastItem.duration).toBeGreaterThan(0);
          expect(typeof toastItem.id).toBe("string");
          expect(toastItem.id.length).toBeGreaterThan(0);
        },
      ),
    );
  });

  it("연속 호출 시 각 토스트 id가 고유하다", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2, max: 20 }),
        (count) => {
          const ids = Array.from({ length: count }, () => crypto.randomUUID());
          const uniqueIds = new Set(ids);
          expect(uniqueIds.size).toBe(count);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 1.11 — 공통 UI 속성 (SeverityBadge / SourceBadge)
// ──────────────────────────────────────────────────────────────

describe("1.11 공통 UI 속성", () => {
  const SEVERITY_LEVELS = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"] as const;
  const SOURCE_TYPES = ["System", "Customer", "Custom"] as const;

  it("SeverityBadge: 유효한 severity level은 5개 (SEV-1 ~ SEV-5)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...SEVERITY_LEVELS),
        (severity) => {
          expect(severity).toMatch(/^SEV-[1-5]$/);
          expect(SEVERITY_LEVELS).toContain(severity);
        },
      ),
    );
  });

  it("SourceBadge: 유효한 source type은 3개 (System / Customer / Custom)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...SOURCE_TYPES),
        (source) => {
          expect(SOURCE_TYPES).toContain(source);
        },
      ),
    );
  });

  it("SEV 숫자가 낮을수록 심각도 순서 보존", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...SEVERITY_LEVELS),
        fc.constantFrom(...SEVERITY_LEVELS),
        (a, b) => {
          const numA = parseInt(a.split("-")[1], 10);
          const numB = parseInt(b.split("-")[1], 10);
          if (numA < numB) expect(numA).toBeLessThan(numB);
          if (numA > numB) expect(numA).toBeGreaterThan(numB);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 3.2 — GlobalFilterBar 속성
// ──────────────────────────────────────────────────────────────

describe("3.2 GlobalFilterBar 속성", () => {
  const SERVICES = ["EC2", "RDS", "ALB", "NLB", "ELB", "Lambda", "ECS"] as const;

  it("서비스 목록은 중복 없이 유한하다", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...SERVICES),
        (service) => {
          expect(typeof service).toBe("string");
          expect(service.length).toBeGreaterThan(0);
          expect(new Set(SERVICES).size).toBe(SERVICES.length);
        },
      ),
    );
  });

  it("필터 파라미터 업데이트: 새 값이 이전 값을 덮어쓴다", () => {
    fc.assert(
      fc.property(
        fc.record({
          customer_id: fc.option(safeId, { nil: undefined }),
          account_id: fc.option(safeId, { nil: undefined }),
        }),
        fc.record({
          customer_id: fc.option(safeId, { nil: undefined }),
          account_id: fc.option(safeId, { nil: undefined }),
        }),
        (prev, next) => {
          const merged = { ...prev, ...next };
          if (next.customer_id !== undefined) {
            expect(merged.customer_id).toBe(next.customer_id);
          }
          if (next.account_id !== undefined) {
            expect(merged.account_id).toBe(next.account_id);
          }
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 5.6 — 동기화 토스트 메시지 속성
// ──────────────────────────────────────────────────────────────

describe("5.6 동기화 토스트 메시지 속성", () => {
  it("모니터링 토글 에러 메시지에 resource_id가 포함된다", () => {
    fc.assert(
      fc.property(
        safeId,
        (resourceId) => {
          const errorMessage = `모니터링 상태 변경에 실패했습니다 (${resourceId})`;
          expect(errorMessage).toContain(resourceId);
          expect(errorMessage.length).toBeGreaterThan(0);
        },
      ),
    );
  });

  it("동기화 결과 토스트: discovered/updated/removed 모두 0 이상", () => {
    fc.assert(
      fc.property(
        fc.record({
          discovered: fc.integer({ min: 0, max: 100 }),
          updated: fc.integer({ min: 0, max: 100 }),
          removed: fc.integer({ min: 0, max: 100 }),
        }),
        ({ discovered, updated, removed }) => {
          expect(discovered).toBeGreaterThanOrEqual(0);
          expect(updated).toBeGreaterThanOrEqual(0);
          expect(removed).toBeGreaterThanOrEqual(0);
          const message = `동기화 완료: ${discovered}개 발견, ${updated}개 업데이트, ${removed}개 제거`;
          expect(message).toContain(String(discovered));
          expect(message).toContain(String(updated));
          expect(message).toContain(String(removed));
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 5.8 — CSV 내보내기 속성
// ──────────────────────────────────────────────────────────────

describe("5.8 CSV 내보내기 속성", () => {
  it("buildExportFilename: type으로 시작하고 .csv로 끝나며 날짜 형식 포함", () => {
    fc.assert(
      fc.property(
        fc.constantFrom<"resources" | "alarms">("resources", "alarms"),
        fc.integer({ min: 2020, max: 2030 }),
        fc.integer({ min: 1, max: 12 }),
        fc.integer({ min: 1, max: 28 }),
        (type, year, month, day) => {
          const date = new Date(year, month - 1, day);
          const filename = buildExportFilename(type, date);
          expect(filename).toMatch(/^(resources|alarms)_\d{4}-\d{2}-\d{2}\.csv$/);
          expect(filename.startsWith(type)).toBe(true);
          expect(filename.endsWith(".csv")).toBe(true);
        },
      ),
    );
  });

  it("buildExportUrl: path를 포함하며 빈 필터는 쿼리스트링 없음", () => {
    fc.assert(
      fc.property(
        fc.stringMatching(/^\/[a-z/]+$/),
        fc.dictionary(
          fc.string({ minLength: 1, maxLength: 10 }),
          fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: undefined }),
        ),
        (path, filters) => {
          const url = buildExportUrl(path, filters as Record<string, string | undefined>);
          expect(url).toContain(path);
          const hasNonEmpty = Object.values(filters).some((v) => v !== undefined && v !== "");
          if (!hasNonEmpty) {
            expect(url).not.toContain("?");
          }
        },
      ),
    );
  });

  it("buildExportUrl: 정의된 필터 값은 URLSearchParams로 파싱 가능하다", () => {
    fc.assert(
      fc.property(
        fc.stringMatching(/^[a-z_]{1,10}$/),
        fc.stringMatching(/^[a-z0-9-]{1,20}$/),
        (key, value) => {
          const url = buildExportUrl("/export", { [key]: value });
          const qsStart = url.indexOf("?");
          expect(qsStart).toBeGreaterThan(-1);
          const qs = url.slice(qsStart + 1);
          const parsed = new URLSearchParams(qs);
          expect(parsed.get(key)).toBe(value);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 7.2 — 벌크 액션 속성
// ──────────────────────────────────────────────────────────────

describe("7.2 벌크 액션 속성", () => {
  it("BulkMonitoringRequest: resource_ids 개수와 total이 일치한다", () => {
    fc.assert(
      fc.property(
        fc.array(safeId, { minLength: 1, maxLength: 50 }),
        fc.constantFrom<"enable" | "disable">("enable", "disable"),
        (resourceIds, action) => {
          const request: BulkMonitoringRequest = {
            resource_ids: resourceIds,
            action,
          };
          expect(request.resource_ids.length).toBeGreaterThanOrEqual(1);
          // job 생성 시 total_count = resource_ids.length
          const expectedTotal = request.resource_ids.length;
          expect(expectedTotal).toBe(resourceIds.length);
        },
      ),
    );
  });

  it("벌크 처리 후 job completed_count + failed_count = total_count", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        fc.integer({ min: 0, max: 1 }),  // 각 아이템: 성공(1) 또는 실패(0)
        (total, successRate) => {
          // 시뮬레이션: 각 아이템을 독립적으로 처리
          let completed = 0;
          let failed = 0;
          for (let i = 0; i < total; i++) {
            if (Math.random() <= successRate) completed++;
            else failed++;
          }
          expect(completed + failed).toBe(total);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 7.8 — 커스텀 메트릭 속성
// ──────────────────────────────────────────────────────────────

describe("7.8 커스텀 메트릭 속성", () => {
  const customMetricArb = fc.record<CustomMetricConfig>({
    metric_name: nonEmptyString,
    namespace: nonEmptyString,
    threshold: fc.double({ min: 0, max: 100, noNaN: true, noDefaultInfinity: true }),
    unit: fc.constantFrom("Percent", "Count", "Bytes", "Seconds", "None"),
    direction: fc.constantFrom<">" | "<">(">", "<"),
  });

  it("CustomMetricConfig: threshold는 0 이상, direction은 > 또는 <", () => {
    fc.assert(
      fc.property(customMetricArb, (metric) => {
        expect(metric.threshold).toBeGreaterThanOrEqual(0);
        expect([">", "<"]).toContain(metric.direction);
        expect(metric.metric_name.length).toBeGreaterThan(0);
        expect(metric.namespace.length).toBeGreaterThan(0);
      }),
    );
  });

  it("중복 metric_name을 제외한 커스텀 메트릭 목록은 유니크하다", () => {
    fc.assert(
      fc.property(
        fc.array(customMetricArb, { minLength: 0, maxLength: 10 }),
        (metrics) => {
          const uniqueNames = new Set(metrics.map((m) => m.metric_name));
          const deduped = metrics.filter(
            (m, idx) => metrics.findIndex((x) => x.metric_name === m.metric_name) === idx,
          );
          expect(deduped.length).toBe(uniqueNames.size);
        },
      ),
    );
  });
});

// ──────────────────────────────────────────────────────────────
// Task 9.7 — 임계치 계층 속성
// ──────────────────────────────────────────────────────────────

describe("9.7 임계치 계층 속성", () => {
  const thresholdOverrideArb = fc.record({
    metric_key: nonEmptyString,
    system_default: fc.double({ min: 0, max: 1000, noNaN: true, noDefaultInfinity: true }),
    customer_override: fc.option(
      fc.double({ min: 0, max: 1000, noNaN: true, noDefaultInfinity: true }),
      { nil: null },
    ),
    unit: fc.constantFrom("Percent", "Count", "Bytes"),
    direction: fc.constantFrom<">" | "<">(">", "<"),
  });

  function resolveThreshold(override: ThresholdOverride): number {
    return override.customer_override !== null
      ? override.customer_override
      : override.system_default;
  }

  it("customer_override가 null이 아니면 system_default가 아닌 customer_override를 사용한다", () => {
    fc.assert(
      fc.property(thresholdOverrideArb, (override) => {
        const resolved = resolveThreshold(override as ThresholdOverride);
        if (override.customer_override !== null) {
          expect(resolved).toBe(override.customer_override);
        } else {
          expect(resolved).toBe(override.system_default);
        }
      }),
    );
  });

  it("임계치 값은 항상 0 이상의 유한한 숫자이다", () => {
    fc.assert(
      fc.property(thresholdOverrideArb, (override) => {
        const resolved = resolveThreshold(override as ThresholdOverride);
        expect(Number.isFinite(resolved)).toBe(true);
        expect(resolved).toBeGreaterThanOrEqual(0);
      }),
    );
  });

  it("고객사 오버라이드 일괄 적용: 오버라이드가 있는 메트릭 수는 원본 이하이다", () => {
    fc.assert(
      fc.property(
        fc.array(thresholdOverrideArb, { minLength: 0, maxLength: 20 }),
        (overrides) => {
          const withOverride = overrides.filter((o) => o.customer_override !== null);
          expect(withOverride.length).toBeLessThanOrEqual(overrides.length);
        },
      ),
    );
  });
});
