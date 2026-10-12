import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AccountSection, unregisteredRegions } from "../AccountSection";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/components/shared/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));
vi.mock("@/lib/api-functions", () => ({
  createAccount: vi.fn(),
  testConnection: vi.fn(),
  updateAccountRegions: vi.fn(async () => ({})),
}));

import { updateAccountRegions } from "@/lib/api-functions";

const customers = [{ customer_id: "home", name: "HOME", provider: "aws" as const, account_count: 1 }];
const account = {
  account_id: "771283576189",
  customer_id: "home",
  name: "HOME-PRD",
  role_arn: "arn:aws:iam::771283576189:role/AlarmManagerMonitoringRole",
  regions: ["ap-northeast-2"],
  connection_status: "connected" as const,
  detected_regions: ["us-east-1", "ap-northeast-2", "ap-northeast-1"],
};

describe("unregisteredRegions", () => {
  it("등록 리전과 항상 도는 버지니아를 뺀다", () => {
    expect(unregisteredRegions(account.detected_regions, account.regions)).toEqual(["ap-northeast-1"]);
    expect(unregisteredRegions(undefined, ["ap-northeast-2"])).toEqual([]);
  });
});

describe("AccountSection — 리전 탐지", () => {
  beforeEach(() => vi.mocked(updateAccountRegions).mockClear());

  it("리소스가 있지만 감시 밖인 리전을 보여주고, 추가하면 등록 리전에 합쳐 저장한다", async () => {
    render(<AccountSection accounts={[account]} customers={customers} />);
    expect(screen.getByText("리소스가 있지만 감시 밖")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "감시 리전에 추가" }));
    await waitFor(() =>
      expect(updateAccountRegions).toHaveBeenCalledWith("771283576189", "home", ["ap-northeast-2", "ap-northeast-1"]),
    );
  });

  it("빠진 리전이 없으면 경고를 그리지 않는다", () => {
    render(<AccountSection accounts={[{ ...account, detected_regions: ["us-east-1", "ap-northeast-2"] }]} customers={customers} />);
    expect(screen.queryByText("리소스가 있지만 감시 밖")).toBeNull();
  });

  it("마지막 남은 리전은 뺄 수 없다", () => {
    render(<AccountSection accounts={[account]} customers={customers} />);
    expect(screen.queryByRole("button", { name: "Remove ap-northeast-2" })).toBeNull();
  });
});
