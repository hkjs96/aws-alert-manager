"use client";

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { GlobalFilterBar } from "../GlobalFilterBar";

// --- Next.js navigation mocks ---
const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/dashboard",
  useSearchParams: () => mockSearchParams,
}));

// --- API function mocks ---
const mockCustomers = [
  { customer_id: "cust-001", name: "Acme Corp", provider: "aws" as const, account_count: 2 },
  { customer_id: "cust-002", name: "Globex Inc", provider: "aws" as const, account_count: 1 },
];

const mockAccounts = [
  { account_id: "acc-001", customer_id: "cust-001", name: "Acme Prod", role_arn: "arn:...", regions: ["us-east-1"], connection_status: "connected" as const },
  { account_id: "acc-002", customer_id: "cust-001", name: "Acme Staging", role_arn: "arn:...", regions: ["us-west-2"], connection_status: "connected" as const },
  { account_id: "acc-003", customer_id: "cust-002", name: "Globex Main", role_arn: "arn:...", regions: ["eu-west-1"], connection_status: "connected" as const },
];

vi.mock("@/lib/api-functions", () => ({
  fetchCustomers: vi.fn(() => Promise.resolve(mockCustomers)),
  fetchAccounts: vi.fn(() => Promise.resolve(mockAccounts)),
}));

// --- useOwnedCustomers mock ---
vi.mock("@/hooks/useOwnedCustomers", () => ({
  useOwnedCustomers: vi.fn(),
}));

import { useOwnedCustomers } from "@/hooks/useOwnedCustomers";

function makeOwnedState(ownedIds: string[]) {
  return {
    ownedCustomerIds: ownedIds,
    isLoading: false,
    toggleOwned: vi.fn(async () => {}),
    isOwned: (id: string) => ownedIds.includes(id),
  };
}

describe("GlobalFilterBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of [...mockSearchParams.keys()]) {
      mockSearchParams.delete(key);
    }
    // 기본: 두 고객사 모두 담당
    vi.mocked(useOwnedCustomers).mockReturnValue(
      makeOwnedState(["cust-001", "cust-002"]),
    );
  });

  it("초기 렌더링 시 3개 드롭다운을 표시한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByLabelText("Customer filter")).toBeInTheDocument();
      expect(screen.getByLabelText("Account filter")).toBeInTheDocument();
      expect(screen.getByLabelText("Service filter")).toBeInTheDocument();
    });
  });

  it("고객사 목록을 API에서 가져와 드롭다운에 표시한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
      expect(screen.getByText("Globex Inc")).toBeInTheDocument();
    });
  });

  it("어카운트 목록을 API에서 가져와 드롭다운에 표시한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Prod")).toBeInTheDocument();
      expect(screen.getByText("Acme Staging")).toBeInTheDocument();
      expect(screen.getByText("Globex Main")).toBeInTheDocument();
    });
  });

  it("기본 옵션으로 All Customers / All Accounts / All Services를 표시한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("All Customers")).toBeInTheDocument();
      expect(screen.getByText("All Accounts")).toBeInTheDocument();
      expect(screen.getByText("All Services")).toBeInTheDocument();
    });
  });

  it("Customer 선택 시 router.push로 URL을 업데이트한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Customer filter"), {
      target: { value: "cust-001" },
    });
    expect(mockPush).toHaveBeenCalledWith(
      expect.stringContaining("customer_id=cust-001"),
    );
  });

  it("Customer 변경 시 Account와 Service를 리셋한다", async () => {
    mockSearchParams.set("account_id", "acc-001");
    mockSearchParams.set("service", "EC2");
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Customer filter"), {
      target: { value: "cust-002" },
    });
    const pushArg = mockPush.mock.calls[0][0] as string;
    expect(pushArg).toContain("customer_id=cust-002");
    expect(pushArg).not.toContain("account_id=");
    expect(pushArg).not.toContain("service=");
  });

  it("Account 변경 시 Service를 리셋한다", async () => {
    mockSearchParams.set("customer_id", "cust-001");
    mockSearchParams.set("service", "EC2");
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Prod")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Account filter"), {
      target: { value: "acc-001" },
    });
    const pushArg = mockPush.mock.calls[0][0] as string;
    expect(pushArg).toContain("account_id=acc-001");
    expect(pushArg).not.toContain("service=");
  });

  it("Service 드롭다운에 EC2, RDS, S3, LAMBDA, ALB 옵션을 표시한다", async () => {
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByLabelText("Service filter")).toBeInTheDocument();
    });
    expect(screen.getByText("EC2")).toBeInTheDocument();
    expect(screen.getByText("RDS")).toBeInTheDocument();
    expect(screen.getByText("S3")).toBeInTheDocument();
    expect(screen.getByText("LAMBDA")).toBeInTheDocument();
    expect(screen.getByText("ALB")).toBeInTheDocument();
  });

  // --- 담당 고객사 필터 관련 ---

  it("OwnedCustomers에 포함된 고객사만 Customer 드롭다운에 나타난다", async () => {
    vi.mocked(useOwnedCustomers).mockReturnValue(makeOwnedState(["cust-001"]));
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    });
    expect(screen.queryByText("Globex Inc")).not.toBeInTheDocument();
  });

  it("OwnedCustomers가 비어있으면 Customer 드롭다운이 disabled되고 placeholder가 표시된다", async () => {
    vi.mocked(useOwnedCustomers).mockReturnValue(makeOwnedState([]));
    render(<GlobalFilterBar />);
    await waitFor(() => {
      const select = screen.getByLabelText("Customer filter");
      expect(select).toBeDisabled();
    });
    expect(screen.getByText("담당 고객사 없음")).toBeInTheDocument();
  });

  it("URL에 OwnedCustomers에 없는 customer_id가 있으면 router.replace로 파라미터를 제거한다", async () => {
    vi.mocked(useOwnedCustomers).mockReturnValue(makeOwnedState(["cust-001"]));
    mockSearchParams.set("customer_id", "cust-002"); // 담당 아닌 고객사
    render(<GlobalFilterBar />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.not.stringContaining("customer_id=cust-002"),
      );
    });
  });
});
