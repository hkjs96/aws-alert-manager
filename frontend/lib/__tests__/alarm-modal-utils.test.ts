import { describe, it, expect } from "vitest";
import { filterAccounts, filterResources, isSubmitEnabled } from "../alarm-modal-utils";
import type { MetricRow } from "@/components/resources/MetricConfigSection";
import type { Account, Resource } from "@/types";

const MOCK_ACCOUNTS: Account[] = [
  { account_id: "882311440092", customer_id: "cust-001", name: "Production", role_arn: "", regions: ["us-east-1"], connection_status: "connected" },
  { account_id: "440911228833", customer_id: "cust-001", name: "Staging", role_arn: "", regions: ["us-west-2"], connection_status: "connected" },
  { account_id: "112233445566", customer_id: "cust-002", name: "Main", role_arn: "", regions: ["ap-northeast-2"], connection_status: "connected" },
];

const MOCK_RESOURCES: Resource[] = [
  { id: "i-001", name: "web-01", type: "EC2", account: "882311440092", region: "us-east-1", monitoring: true, alarm_count: 1, alarms: { critical: 0, warning: 1 }, inventory_source: "aws", persisted: true, status: "active" },
  { id: "i-002", name: "web-02", type: "EC2", account: "882311440092", region: "us-east-1", monitoring: false, alarm_count: 0, alarms: { critical: 0, warning: 0 }, inventory_source: "aws", persisted: true, status: "active" },
  { id: "i-003", name: "api-01", type: "EC2", account: "112233445566", region: "ap-northeast-2", monitoring: true, alarm_count: 0, alarms: { critical: 0, warning: 0 }, inventory_source: "aws", persisted: true, status: "active" },
];

describe("filterAccounts", () => {
  it("customer_id가 일치하는 어카운트만 반환한다", () => {
    const result = filterAccounts(MOCK_ACCOUNTS, "cust-001");
    expect(result).toHaveLength(2);
    expect(result.every((a) => a.customer_id === "cust-001")).toBe(true);
  });

  it("일치하는 어카운트가 없으면 빈 배열을 반환한다", () => {
    const result = filterAccounts(MOCK_ACCOUNTS, "nonexistent");
    expect(result).toEqual([]);
  });

  it("빈 배열이 입력되면 빈 배열을 반환한다", () => {
    const result = filterAccounts([], "cust-001");
    expect(result).toEqual([]);
  });
});

describe("filterResources", () => {
  it("트랙 1: account 일치 + monitoring=true인 리소스만 반환한다", () => {
    const result = filterResources(MOCK_RESOURCES, "882311440092", 1);
    expect(result.length).toBeGreaterThan(0);
    expect(result.every((r) => r.account === "882311440092" && r.monitoring === true)).toBe(true);
  });

  it("트랙 2: account 일치 + monitoring=false인 리소스만 반환한다", () => {
    const result = filterResources(MOCK_RESOURCES, "882311440092", 2);
    expect(result.length).toBeGreaterThan(0);
    expect(result.every((r) => r.account === "882311440092" && r.monitoring === false)).toBe(true);
  });

  it("조건에 맞는 리소스가 없으면 빈 배열을 반환한다", () => {
    const result = filterResources(MOCK_RESOURCES, "nonexistent", 1);
    expect(result).toEqual([]);
  });

  it("빈 배열이 입력되면 빈 배열을 반환한다", () => {
    const result = filterResources([], "882311440092", 1);
    expect(result).toEqual([]);
  });
});

describe("isSubmitEnabled", () => {
  const makeMetric = (enabled: boolean): MetricRow => ({
    key: "CPU", name: "CPUUtilization", threshold: 80, unit: "%", direction: ">", enabled,
  });

  it("트랙 1: 커스텀 메트릭이 1개 이상이면 true", () => {
    expect(isSubmitEnabled(1, [], [makeMetric(true)])).toBe(true);
  });

  it("트랙 1: 커스텀 메트릭이 0개이면 false", () => {
    expect(isSubmitEnabled(1, [], [])).toBe(false);
  });

  it("트랙 1: 기본 메트릭이 있어도 커스텀 메트릭이 없으면 false", () => {
    expect(isSubmitEnabled(1, [makeMetric(true)], [])).toBe(false);
  });

  it("트랙 2: 기본 메트릭 중 1개 이상 enabled이면 true", () => {
    expect(isSubmitEnabled(2, [makeMetric(true), makeMetric(false)], [])).toBe(true);
  });

  it("트랙 2: 모든 기본 메트릭 비활성화 + 커스텀 메트릭 1개 이상이면 true", () => {
    expect(isSubmitEnabled(2, [makeMetric(false)], [makeMetric(true)])).toBe(true);
  });

  it("트랙 2: 모든 기본 메트릭 비활성화 + 커스텀 메트릭 0개이면 false", () => {
    expect(isSubmitEnabled(2, [makeMetric(false)], [])).toBe(false);
  });
});
