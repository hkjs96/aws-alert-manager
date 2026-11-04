import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CustomerSection, parseManagers } from "../CustomerSection";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
const showToast = vi.fn();
vi.mock("@/components/shared/Toast", () => ({ useToast: () => ({ showToast }) }));
vi.mock("@/hooks/useMe", () => ({ useMe: vi.fn() }));
vi.mock("@/lib/api-functions", () => ({
  createCustomer: vi.fn(),
  deleteCustomer: vi.fn(),
  updateCustomer: vi.fn(async () => ({})),
}));

import { useMe } from "@/hooks/useMe";
import { updateCustomer } from "@/lib/api-functions";

const customers = [
  { customer_id: "EMU-EM2", name: "EMU-EM2", provider: "aws" as const, account_count: 1, managers: ["koo@mz.co.kr", "sxt@mz.co.kr"] },
  { customer_id: "HOME", name: "HOME", provider: "aws" as const, account_count: 1, managers: ["tlsgks678@mz.co.kr"] },
  { customer_id: "NEW", name: "NEW", provider: "aws" as const, account_count: 0 },
];

const me = (email: string, isAdmin: boolean) =>
  vi.mocked(useMe).mockReturnValue({ email, isAdmin, isLoading: false });

describe("parseManagers", () => {
  it("쉼표·공백으로 나누고 소문자·중복 제거", () => {
    expect(parseManagers(" A@mz.co.kr, b@mz.co.kr\na@mz.co.kr ")).toEqual(["a@mz.co.kr", "b@mz.co.kr"]);
  });
});

describe("CustomerSection — 담당자(접근 권한)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("담당자를 보여주고, 담당자가 없는 고객사는 관리자만 볼 수 있다고 표시한다", () => {
    me("tlsgks678@mz.co.kr", true);
    render(<CustomerSection customers={customers} />);
    expect(screen.getByText("koo@mz.co.kr, sxt@mz.co.kr")).toBeInTheDocument();
    expect(screen.getByText(/None — visible to admins only/)).toBeInTheDocument();
  });

  it("관리자는 모든 고객사를 편집할 수 있다", () => {
    me("tlsgks678@mz.co.kr", true);
    render(<CustomerSection customers={customers} />);
    expect(screen.getAllByRole("button", { name: /Edit managers for/ })).toHaveLength(3);
  });

  it("일반 사용자는 자기가 담당인 고객사만 편집할 수 있다", () => {
    me("koo@mz.co.kr", false);
    render(<CustomerSection customers={customers} />);
    const edits = screen.getAllByRole("button", { name: /Edit managers for/ });
    expect(edits).toHaveLength(1);
    expect(edits[0]).toHaveAccessibleName("Edit managers for EMU-EM2");
    expect(screen.getByText(/Only customers you manage are shown/)).toBeInTheDocument();
  });

  it("편집해서 저장하면 정리된 목록으로 업데이트한다", async () => {
    me("koo@mz.co.kr", false);
    render(<CustomerSection customers={customers} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit managers for EMU-EM2" }));
    fireEvent.change(screen.getByLabelText("Managers for EMU-EM2"), { target: { value: "koo@mz.co.kr, NEW@mz.co.kr" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() =>
      expect(updateCustomer).toHaveBeenCalledWith("EMU-EM2", { managers: ["koo@mz.co.kr", "new@mz.co.kr"] }),
    );
  });

  it("빈 목록이나 잘못된 이메일은 저장하지 않는다", () => {
    me("tlsgks678@mz.co.kr", true);
    render(<CustomerSection customers={customers} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit managers for HOME" }));
    fireEvent.change(screen.getByLabelText("Managers for HOME"), { target: { value: "  " } });
    fireEvent.click(screen.getByText("Save"));
    fireEvent.change(screen.getByLabelText("Managers for HOME"), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByText("Save"));
    expect(updateCustomer).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledTimes(2);
  });

  it("일반 사용자가 본인을 빼려 하면 확인을 받고, 취소하면 저장하지 않는다", () => {
    me("koo@mz.co.kr", false);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<CustomerSection customers={customers} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit managers for EMU-EM2" }));
    fireEvent.change(screen.getByLabelText("Managers for EMU-EM2"), { target: { value: "sxt@mz.co.kr" } });
    fireEvent.click(screen.getByText("Save"));
    expect(confirm).toHaveBeenCalled();
    expect(updateCustomer).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});
