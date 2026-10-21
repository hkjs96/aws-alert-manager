import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ToastProvider } from "@/components/shared/Toast";
import { ResourcesContent } from "../ResourcesContent";
import { encodeResourceId } from "@/lib/resource-id";
import type { Resource } from "@/types";

const mockRouterPush = vi.hoisted(() => vi.fn());
const mockRouterRefresh = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api-functions", () => ({
  toggleMonitoring: vi.fn().mockResolvedValue({ resource_id: "i-001", monitoring: false, status: "updated" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush, refresh: mockRouterRefresh }),
}));

const resources: Resource[] = [
  {
    id: "i-001",
    name: "web-01",
    type: "EC2",
    account: "111111111111",
    region: "us-east-1",
    monitoring: true,
    alarm_count: 0,
    alarms: { critical: 0, warning: 0 },
    inventory_source: "aws",
    persisted: true,
    status: "active",
  },
];

function renderContent() {
  return render(
    <ToastProvider>
      <ResourcesContent
        resources={resources}
        customers={[{ id: "cust-1", name: "Customer 1" }]}
        accounts={[{ id: "111111111111", name: "Account 1", customerId: "cust-1" }]}
      />
    </ToastProvider>,
  );
}

describe("ResourcesContent monitoring toggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requires confirmation before toggling from the inventory table", async () => {
    const { toggleMonitoring } = await import("@/lib/api-functions");
    renderContent();

    fireEvent.click(screen.getByRole("button", { name: "Turn monitoring off" }));

    expect(screen.getByText("Turn monitoring off?")).toBeInTheDocument();
    expect(toggleMonitoring).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Turn Off"));

    await waitFor(() => {
      expect(toggleMonitoring).toHaveBeenCalledWith("i-001", false);
    });
  });

  it("does not call the API when the confirmation is cancelled", async () => {
    const { toggleMonitoring } = await import("@/lib/api-functions");
    renderContent();

    fireEvent.click(screen.getByRole("button", { name: "Turn monitoring off" }));
    fireEvent.click(screen.getByText("Cancel"));

    expect(screen.queryByText("Turn monitoring off?")).not.toBeInTheDocument();
    expect(toggleMonitoring).not.toHaveBeenCalled();
  });

  it("navigates to resource detail by encoded resource id", () => {
    renderContent();

    fireEvent.click(screen.getByText("web-01"));

    // resource_id는 base64url 토큰으로 인코딩되어 path에 실린다 (AGENTS.md AP-6).
    expect(mockRouterPush).toHaveBeenCalledWith(`/resources/${encodeResourceId("i-001")}`);
  });
});

describe("ResourcesContent 글로벌 범위(customer/account props)", () => {
  const two: Resource[] = [
    resources[0]!,
    { ...resources[0]!, id: "i-002", name: "api-02", account: "222222222222" },
  ];
  const customers = [{ id: "cust-1", name: "Customer 1" }, { id: "cust-2", name: "Customer 2" }];
  const accounts = [
    { id: "111111111111", name: "Account 1", customerId: "cust-1" },
    { id: "222222222222", name: "Account 2", customerId: "cust-2" },
  ];

  function renderScoped(customerFilter: string) {
    return (
      <ToastProvider>
        <ResourcesContent resources={two} customers={customers} accounts={accounts} customerFilter={customerFilter} />
      </ToastProvider>
    );
  }

  it("customerFilter prop의 계정 리소스만 보이고, prop이 바뀌면 다시 거른다", () => {
    const { rerender } = render(renderScoped("cust-2"));
    expect(screen.getByText("api-02")).toBeInTheDocument();
    expect(screen.queryByText("web-01")).not.toBeInTheDocument();

    rerender(renderScoped(""));
    expect(screen.getByText("api-02")).toBeInTheDocument();
    expect(screen.getByText("web-01")).toBeInTheDocument();
  });

  it("페이지 안 필터 바에는 고객사·계정 선택이 없다", () => {
    render(renderScoped(""));
    expect(screen.queryByText("All Customers")).not.toBeInTheDocument();
    expect(screen.queryByText("All Accounts")).not.toBeInTheDocument();
  });
});
