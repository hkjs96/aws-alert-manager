import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ToastProvider } from "@/components/shared/Toast";
import { ResourcesContent } from "../ResourcesContent";
import type { Resource } from "@/types";

vi.mock("@/lib/api-functions", () => ({
  toggleMonitoring: vi.fn().mockResolvedValue({ resource_id: "i-001", monitoring: false, status: "updated" }),
}));

vi.mock("@/hooks/useOwnedCustomers", () => ({
  useOwnedCustomers: () => ({
    ownedCustomerIds: ["cust-1"],
    isLoading: false,
    toggleOwned: vi.fn(),
    isOwned: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
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
});
