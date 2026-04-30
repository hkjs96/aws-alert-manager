import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToastProvider } from "@/components/shared/Toast";
import { DashboardContent } from "../DashboardContent";

// next/navigation mock
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

// useOwnedCustomers mock — localStorage가 비어있으면 OwnedEmptyState가 렌더링되므로 강제로 값 주입
vi.mock("@/hooks/useOwnedCustomers", () => ({
  useOwnedCustomers: () => ({
    ownedCustomerIds: ["cust-001"],
    addOwnedCustomer: vi.fn(),
    removeOwnedCustomer: vi.fn(),
  }),
}));

// api-functions mock (CreateAlarmModal 내부에서 호출)
vi.mock("@/lib/api-functions", () => ({
  fetchResources: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 }),
  fetchCustomers: vi.fn().mockResolvedValue([]),
  fetchAccounts: vi.fn().mockResolvedValue([]),
}));

const defaultProps = {
  stats: { monitored_count: 0, active_alarms: 0, alarm_summary: { critical: 0, warning: 0, ok: 0 } },
  alarms: [],
  customers: [],
  accounts: [],
};

function renderDashboard() {
  return render(
    <ToastProvider>
      <DashboardContent {...defaultProps} />
    </ToastProvider>,
  );
}

describe("DashboardContent — Create Alarm 연동 (9.2)", () => {
  it("초기에 모달이 열려 있지 않다", () => {
    renderDashboard();
    expect(screen.queryByTestId("create-alarm-modal")).not.toBeInTheDocument();
  });

  it("'Create Alarm' 버튼 클릭 시 CreateAlarmModal이 열린다", () => {
    renderDashboard();
    fireEvent.click(screen.getByText("Create Alarm"));
    expect(screen.getByTestId("create-alarm-modal")).toBeInTheDocument();
  });

  it("모달의 닫기 버튼 클릭 시 모달이 닫힌다", () => {
    renderDashboard();
    fireEvent.click(screen.getByText("Create Alarm"));
    expect(screen.getByTestId("create-alarm-modal")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("close-button"));
    expect(screen.queryByTestId("create-alarm-modal")).not.toBeInTheDocument();
  });
});
