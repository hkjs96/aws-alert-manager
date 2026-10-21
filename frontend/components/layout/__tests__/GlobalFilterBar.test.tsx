import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { GlobalFilterBar, GLOBAL_SCOPE_STORAGE_KEY } from "../GlobalFilterBar";

// --- Next.js navigation mocks ---
const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/dashboard",
}));

const mockCustomers = [
  { customer_id: "cust-001", name: "Acme Corp", provider: "aws" as const, account_count: 2 },
  { customer_id: "cust-002", name: "Globex Inc", provider: "aws" as const, account_count: 1 },
];

const mockAccounts = [
  { account_id: "acc-001", customer_id: "cust-001", name: "Acme Prod", role_arn: "arn:...", regions: ["us-east-1"], connection_status: "connected" as const },
  { account_id: "acc-002", customer_id: "cust-001", name: "Acme Staging", role_arn: "arn:...", regions: ["us-west-2"], connection_status: "connected" as const },
  { account_id: "acc-003", customer_id: "cust-002", name: "Globex Main", role_arn: "arn:...", regions: ["eu-west-1"], connection_status: "connected" as const },
];

// 고객사/어카운트는 서버 컴포넌트(GlobalFilterOptions)가 props로 내려준다 — 클라이언트 fetch 없음.
function renderBar() {
  return render(<GlobalFilterBar customers={mockCustomers} accounts={mockAccounts} />);
}

describe("GlobalFilterBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    window.history.replaceState(null, "", "/dashboard");
  });

  it("고객사·계정 드롭다운만 표시하고 서비스 드롭다운은 없다", () => {
    renderBar();
    expect(screen.getByLabelText("Customer filter")).toBeInTheDocument();
    expect(screen.getByLabelText("Account filter")).toBeInTheDocument();
    expect(screen.queryByLabelText("Service filter")).not.toBeInTheDocument();
    expect(screen.getByText("전체 고객사")).toBeInTheDocument();
    expect(screen.getByText("전체 계정")).toBeInTheDocument();
  });

  it("props로 받은 고객사·계정을 모두 표시한다", () => {
    renderBar();
    for (const name of ["Acme Corp", "Globex Inc", "Acme Prod", "Acme Staging", "Globex Main"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("고객사 변경 시 customer 파라미터를 쓰고 account를 지우며 저장한다", () => {
    window.history.replaceState(null, "", "/dashboard?customer=cust-001&account=acc-001");
    renderBar();
    fireEvent.change(screen.getByLabelText("Customer filter"), { target: { value: "cust-002" } });
    const pushArg = mockPush.mock.calls[0]![0] as string;
    expect(pushArg).toContain("customer=cust-002");
    expect(pushArg).not.toContain("account=");
    expect(pushArg).not.toContain("customer_id=");
    expect(JSON.parse(localStorage.getItem(GLOBAL_SCOPE_STORAGE_KEY)!)).toEqual({ customer: "cust-002", account: "" });
  });

  it("고객사를 고르면 그 고객사의 계정만 보인다", async () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Customer filter"), { target: { value: "cust-002" } });
    await waitFor(() => expect(screen.queryByText("Acme Prod")).not.toBeInTheDocument());
    expect(screen.getByText("Globex Main")).toBeInTheDocument();
  });

  it("전체 고객사를 고르면 저장된 범위를 지운다", () => {
    localStorage.setItem(GLOBAL_SCOPE_STORAGE_KEY, JSON.stringify({ customer: "cust-001", account: "" }));
    window.history.replaceState(null, "", "/dashboard?customer=cust-001");
    renderBar();
    fireEvent.change(screen.getByLabelText("Customer filter"), { target: { value: "" } });
    expect(localStorage.getItem(GLOBAL_SCOPE_STORAGE_KEY)).toBeNull();
    expect(mockPush).toHaveBeenCalledWith("/dashboard");
  });

  it("URL에 customer가 없으면 저장된 고객사·계정을 router.replace로 복원한다", async () => {
    localStorage.setItem(GLOBAL_SCOPE_STORAGE_KEY, JSON.stringify({ customer: "cust-001", account: "acc-002" }));
    renderBar();
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard?customer=cust-001&account=acc-002");
    });
  });

  it("저장된 계정이 그 고객사 소속이 아니면 고객사만 복원한다", async () => {
    localStorage.setItem(GLOBAL_SCOPE_STORAGE_KEY, JSON.stringify({ customer: "cust-001", account: "acc-003" }));
    renderBar();
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard?customer=cust-001");
    });
  });

  it("저장된 고객사가 목록에 없으면 복원하지 않는다", () => {
    localStorage.setItem(GLOBAL_SCOPE_STORAGE_KEY, JSON.stringify({ customer: "cust-999", account: "" }));
    renderBar();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("URL의 고객사가 목록에 없으면 범위 밖이므로 제거한다", async () => {
    window.history.replaceState(null, "", "/dashboard?customer=cust-999&account=acc-001&state=ALARM");
    renderBar();
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard?state=ALARM");
    });
  });

  it("뒤로가기(popstate) 시 URL을 다시 읽는다", async () => {
    renderBar();
    window.history.replaceState(null, "", "/dashboard?customer=cust-002");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => {
      expect(screen.getByLabelText("Customer filter")).toHaveValue("cust-002");
    });
  });
});
