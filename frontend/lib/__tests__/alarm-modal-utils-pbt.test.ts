/**
 * alarm-modal-utils 속성 기반 테스트 (Property-Based Testing)
 *
 * Property 4: filterAccounts 어카운트 필터링 정확성
 * Property 5: filterResources 트랙별 리소스 필터링 정확성
 * Property 9: isSubmitEnabled Submit 버튼 활성화 조건 정합성
 */

import { describe, it } from "vitest";
import * as fc from "fast-check";
import { filterAccounts, filterResources, isSubmitEnabled, type Track } from "../alarm-modal-utils";
import type { Account, Resource } from "@/types";
import type { MetricRow } from "@/components/resources/MetricConfigSection";

// ──────────────────────────────────────────────
// Arbitraries
// ──────────────────────────────────────────────

const customerIdArb = fc.stringMatching(/^cust-[0-9]{3}$/).map((s) => s as string);

const accountArb = fc.record<Account>({
  account_id: fc.stringMatching(/^[0-9]{12}$/),
  customer_id: customerIdArb,
  name: fc.string({ minLength: 1, maxLength: 20 }),
  role_arn: fc.constant("arn:aws:iam::123456789012:role/Test"),
  regions: fc.constant(["ap-northeast-2"]),
  connection_status: fc.constantFrom("connected", "failed", "untested"),
});

const resourceArb = fc.record<Resource>({
  id: fc.uuid(),
  name: fc.string({ minLength: 1, maxLength: 20 }),
  type: fc.constantFrom("EC2", "RDS", "ALB"),
  account: fc.stringMatching(/^[0-9]{12}$/),
  region: fc.constant("ap-northeast-2"),
  monitoring: fc.boolean(),
  alarms: fc.record({ critical: fc.nat(5), warning: fc.nat(5) }),
  alarm_count: fc.nat(10),
  inventory_source: fc.constantFrom("aws", "db", "alarms"),
  persisted: fc.boolean(),
  status: fc.constantFrom("active", "missing", "deleted", "orphan_candidate"),
});

const metricRowArb = (enabled?: boolean): fc.Arbitrary<MetricRow> =>
  fc.record<MetricRow>({
    key: fc.string({ minLength: 1, maxLength: 10 }),
    name: fc.string({ minLength: 1, maxLength: 20 }),
    threshold: fc.double({ min: 0, max: 100, noNaN: true }),
    unit: fc.constantFrom("%", "Count", "Bytes"),
    direction: fc.constantFrom(">", "<"),
    enabled: enabled !== undefined ? fc.constant(enabled) : fc.boolean(),
  });

// ──────────────────────────────────────────────
// Property 4: filterAccounts 정확성
// ──────────────────────────────────────────────

describe("Property 4: filterAccounts 어카운트 필터링 정확성", () => {
  it("반환된 모든 어카운트의 customer_id가 요청한 customer_id와 일치한다", () => {
    fc.assert(
      fc.property(
        fc.array(accountArb, { minLength: 0, maxLength: 20 }),
        customerIdArb,
        (accounts, customerId) => {
          const result = filterAccounts(accounts, customerId);
          return result.every((a) => a.customer_id === customerId);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("조건을 만족하는 모든 어카운트가 빠짐없이 반환된다 (완전성)", () => {
    fc.assert(
      fc.property(
        fc.array(accountArb, { minLength: 0, maxLength: 20 }),
        customerIdArb,
        (accounts, customerId) => {
          const result = filterAccounts(accounts, customerId);
          const expected = accounts.filter((a) => a.customer_id === customerId);
          return result.length === expected.length;
        },
      ),
      { numRuns: 100 },
    );
  });

  it("결과 크기는 입력 배열 크기를 초과하지 않는다", () => {
    fc.assert(
      fc.property(
        fc.array(accountArb, { minLength: 0, maxLength: 20 }),
        customerIdArb,
        (accounts, customerId) => {
          const result = filterAccounts(accounts, customerId);
          return result.length <= accounts.length;
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ──────────────────────────────────────────────
// Property 5: filterResources 트랙별 필터링 정확성
// ──────────────────────────────────────────────

describe("Property 5: filterResources 트랙별 리소스 필터링 정확성", () => {
  it("반환된 리소스가 모두 account 조건을 만족한다", () => {
    fc.assert(
      fc.property(
        fc.array(resourceArb, { minLength: 0, maxLength: 30 }),
        fc.stringMatching(/^[0-9]{12}$/),
        fc.constantFrom(1 as Track, 2 as Track),
        (resources, accountId, track) => {
          const result = filterResources(resources, accountId, track);
          return result.every((r) => r.account === accountId);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("트랙 1: 반환된 리소스가 모두 monitoring=true이다", () => {
    fc.assert(
      fc.property(
        fc.array(resourceArb, { minLength: 0, maxLength: 30 }),
        fc.stringMatching(/^[0-9]{12}$/),
        (resources, accountId) => {
          const result = filterResources(resources, accountId, 1);
          return result.every((r) => r.monitoring === true);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("트랙 2: 반환된 리소스가 모두 monitoring=false이다", () => {
    fc.assert(
      fc.property(
        fc.array(resourceArb, { minLength: 0, maxLength: 30 }),
        fc.stringMatching(/^[0-9]{12}$/),
        (resources, accountId) => {
          const result = filterResources(resources, accountId, 2);
          return result.every((r) => r.monitoring === false);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("조건을 만족하는 모든 리소스가 빠짐없이 반환된다 (완전성)", () => {
    fc.assert(
      fc.property(
        fc.array(resourceArb, { minLength: 0, maxLength: 30 }),
        fc.stringMatching(/^[0-9]{12}$/),
        fc.constantFrom(1 as Track, 2 as Track),
        (resources, accountId, track) => {
          const result = filterResources(resources, accountId, track);
          const monitoringFlag = track === 1;
          const expected = resources.filter(
            (r) => r.account === accountId && r.monitoring === monitoringFlag,
          );
          return result.length === expected.length;
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ──────────────────────────────────────────────
// Property 9: isSubmitEnabled 활성화 조건 정합성
// ──────────────────────────────────────────────

describe("Property 9: isSubmitEnabled Submit 버튼 활성화 조건 정합성", () => {
  it("트랙 1: customMetrics >= 1이면 항상 true, 0이면 항상 false", () => {
    fc.assert(
      fc.property(
        fc.array(metricRowArb(), { minLength: 0, maxLength: 5 }),  // metrics (ignored)
        fc.array(metricRowArb(), { minLength: 0, maxLength: 5 }),  // customMetrics
        (metrics, customMetrics) => {
          const result = isSubmitEnabled(1, metrics, customMetrics);
          const expected = customMetrics.length >= 1;
          return result === expected;
        },
      ),
      { numRuns: 200 },
    );
  });

  it("트랙 2: enabled 기본 메트릭 >= 1이면 true (customMetrics 무관)", () => {
    fc.assert(
      fc.property(
        fc.array(metricRowArb(true), { minLength: 1, maxLength: 5 }),  // 최소 1개 enabled
        fc.array(metricRowArb(), { minLength: 0, maxLength: 5 }),
        (enabledMetrics, customMetrics) => {
          return isSubmitEnabled(2, enabledMetrics, customMetrics) === true;
        },
      ),
      { numRuns: 100 },
    );
  });

  it("트랙 2: 기본 메트릭 전부 disabled + customMetrics >= 1이면 true", () => {
    fc.assert(
      fc.property(
        fc.array(metricRowArb(false), { minLength: 0, maxLength: 5 }),  // 전부 disabled
        fc.array(metricRowArb(), { minLength: 1, maxLength: 5 }),  // 최소 1개 custom
        (disabledMetrics, customMetrics) => {
          return isSubmitEnabled(2, disabledMetrics, customMetrics) === true;
        },
      ),
      { numRuns: 100 },
    );
  });

  it("트랙 2: 기본 메트릭 전부 disabled + customMetrics 0개면 false", () => {
    fc.assert(
      fc.property(
        fc.array(metricRowArb(false), { minLength: 0, maxLength: 5 }),
        (disabledMetrics) => {
          return isSubmitEnabled(2, disabledMetrics, []) === false;
        },
      ),
      { numRuns: 100 },
    );
  });

  it("결과는 항상 boolean이다", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(1 as Track, 2 as Track),
        fc.array(metricRowArb(), { minLength: 0, maxLength: 5 }),
        fc.array(metricRowArb(), { minLength: 0, maxLength: 5 }),
        (track, metrics, customMetrics) => {
          const result = isSubmitEnabled(track, metrics, customMetrics);
          return typeof result === "boolean";
        },
      ),
      { numRuns: 200 },
    );
  });
});
