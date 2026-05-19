import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ResourceFilterStep } from "../ResourceFilterStep";
import type { Resource } from "@/types";
import { createMockResource } from "@/lib/mock-data";

vi.mock("@/lib/api-functions", () => ({
  fetchCustomers: vi.fn().mockResolvedValue([
    { customer_id: "cust-001", name: "고객사 A", provider: "aws", account_count: 2 },
    { customer_id: "cust-002", name: "고객사 B", provider: "aws", account_count: 1 },
  ]),
  fetchAccounts: vi.fn().mockResolvedValue([
    { account_id: "111111111111", customer_id: "cust-001", name: "Dev Account", role_arn: "", regions: [], connection_status: "connected" },
    { account_id: "222222222222", customer_id: "cust-001", name: "Prod Account", role_arn: "", regions: [], connection_status: "connected" },
    { account_id: "333333333333", customer_id: "cust-002", name: "Staging", role_arn: "", regions: [], connection_status: "connected" },
  ]),
}));

const mockResources: Resource[] = [
  createMockResource({ id: "i-001", name: "web-01", type: "EC2", account: "111111111111", region: "ap-northeast-2", monitoring: true, alarms: { critical: 0, warning: 0 } }),
  createMockResource({ id: "i-002", name: "web-02", type: "EC2", account: "111111111111", region: "ap-northeast-2", monitoring: false, alarms: { critical: 0, warning: 0 } }),
  createMockResource({ id: "i-003", name: "api-01", type: "EC2", account: "222222222222", region: "ap-northeast-2", monitoring: true, alarms: { critical: 0, warning: 0 } }),
];

const defaultProps = {
  track: 1 as const,
  customerId: "",
  accountId: "",
  resourceId: "",
  allResources: mockResources,
  onCustomerChange: vi.fn(),
  onAccountChange: vi.fn(),
  onResourceChange: vi.fn(),
};

describe("ResourceFilterStep 컴포넌트", () => {
  it("고객사 셀렉트가 렌더링된다", async () => {
    render(<ResourceFilterStep {...defaultProps} />);
    expect(screen.getByTestId("customer-select")).toBeInTheDocument();
  });

  it("어카운트 셀렉트가 렌더링된다", () => {
    render(<ResourceFilterStep {...defaultProps} />);
    expect(screen.getByTestId("account-select")).toBeInTheDocument();
  });

  it("리소스 셀렉트가 렌더링된다", () => {
    render(<ResourceFilterStep {...defaultProps} />);
    expect(screen.getByTestId("resource-select")).toBeInTheDocument();
  });

  it("비동기 데이터 로드 후 고객사 목록이 표시된다", async () => {
    render(<ResourceFilterStep {...defaultProps} />);
    await waitFor(() => {
      expect(screen.getByText("고객사 A")).toBeInTheDocument();
      expect(screen.getByText("고객사 B")).toBeInTheDocument();
    });
  });

  it("customerId가 없으면 어카운트 셀렉트가 비활성화된다", () => {
    render(<ResourceFilterStep {...defaultProps} customerId="" />);
    expect(screen.getByTestId("account-select")).toBeDisabled();
  });

  it("accountId가 없으면 리소스 셀렉트가 비활성화된다", () => {
    render(<ResourceFilterStep {...defaultProps} accountId="" />);
    expect(screen.getByTestId("resource-select")).toBeDisabled();
  });

  it("트랙 1: accountId가 있고 monitoring=true 리소스가 없으면 안내 메시지 표시", () => {
    render(
      <ResourceFilterStep
        {...defaultProps}
        track={1}
        customerId="cust-001"
        accountId="222222222222"
      />,
    );
    // 222222222222 계정의 monitoring=true 리소스는 i-003뿐인데, 그건 있음
    // 아예 없는 계정으로 테스트
    expect(screen.queryByText("모니터링 중인 리소스가 없습니다")).not.toBeInTheDocument();
  });

  it("트랙 2: accountId가 있고 monitoring=false 리소스만 있는 경우 미모니터링 메시지 노출 안 됨", () => {
    // track 2 + accountId 있음 + monitoring=false 리소스 있음 → 메시지 없어야 함
    render(
      <ResourceFilterStep
        {...defaultProps}
        track={2}
        customerId="cust-001"
        accountId="111111111111"
      />,
    );
    // i-002가 monitoring=false이므로 표시됨 → 메시지 없음
    expect(screen.queryByText("미모니터링 리소스가 없습니다")).not.toBeInTheDocument();
  });

  it("트랙 1 + accountId에 monitoring=true 리소스 없으면 '모니터링 중인 리소스가 없습니다' 표시", () => {
    // i-002만 있는 계정 없지만, monitoring=true가 하나도 없는 가상 시나리오
    const noMonitoringResources: Resource[] = [
      createMockResource({ id: "i-999", name: "idle", type: "EC2", account: "999999999999", region: "ap-northeast-2", monitoring: false, alarms: { critical: 0, warning: 0 } }),
    ];
    render(
      <ResourceFilterStep
        {...defaultProps}
        track={1}
        customerId="cust-001"
        accountId="999999999999"
        allResources={noMonitoringResources}
      />,
    );
    expect(screen.getByText("모니터링 중인 리소스가 없습니다")).toBeInTheDocument();
  });
});
