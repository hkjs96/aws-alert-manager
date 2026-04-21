import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CustomerSection } from "../CustomerSection";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/components/shared/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));
vi.mock("@/hooks/useOwnedCustomers", () => ({
  useOwnedCustomers: vi.fn(),
}));

import { useOwnedCustomers } from "@/hooks/useOwnedCustomers";

const mockCustomers = [
  { customer_id: "cust-a", name: "고객사 A", provider: "aws" as const, account_count: 2 },
  { customer_id: "cust-b", name: "고객사 B", provider: "aws" as const, account_count: 1 },
];

function makeOwnedState(ownedIds: string[]) {
  return {
    ownedCustomerIds: ownedIds,
    isLoading: false,
    toggleOwned: vi.fn(async () => {}),
    isOwned: (id: string) => ownedIds.includes(id),
  };
}

describe("CustomerSection — 담당 체크박스", () => {
  beforeEach(() => {
    vi.mocked(useOwnedCustomers).mockReturnValue(makeOwnedState(["cust-a"]));
  });

  it("각 고객사 행에 담당 체크박스를 렌더한다", () => {
    render(<CustomerSection customers={mockCustomers} />);
    const checkboxes = screen.getAllByRole("checkbox", { name: /담당/i });
    expect(checkboxes).toHaveLength(2);
  });

  it("OwnedCustomers에 포함된 고객사 행의 체크박스가 체크된 상태로 렌더된다", () => {
    render(<CustomerSection customers={mockCustomers} />);
    const checkboxes = screen.getAllByRole("checkbox", { name: /담당/i });
    expect(checkboxes[0]).toBeChecked();   // cust-a (owned)
    expect(checkboxes[1]).not.toBeChecked(); // cust-b (not owned)
  });

  it("담당 체크박스를 토글하면 toggleOwned가 호출된다", async () => {
    const toggleOwned = vi.fn(async () => {});
    vi.mocked(useOwnedCustomers).mockReturnValue({
      ...makeOwnedState(["cust-a"]),
      toggleOwned,
    });
    render(<CustomerSection customers={mockCustomers} />);
    const checkboxes = screen.getAllByRole("checkbox", { name: /담당/i });
    fireEvent.click(checkboxes[1]); // cust-b
    expect(toggleOwned).toHaveBeenCalledWith("cust-b");
  });

  it("OwnedCustomers가 비어있을 때 안내 배너가 표시된다", () => {
    vi.mocked(useOwnedCustomers).mockReturnValue(makeOwnedState([]));
    render(<CustomerSection customers={mockCustomers} />);
    expect(
      screen.getByText(/담당 고객사를 선택하면/i),
    ).toBeInTheDocument();
  });

  it("OwnedCustomers가 비어있지 않으면 안내 배너가 없다", () => {
    render(<CustomerSection customers={mockCustomers} />);
    expect(
      screen.queryByText(/담당 고객사를 선택하면/i),
    ).not.toBeInTheDocument();
  });
});
