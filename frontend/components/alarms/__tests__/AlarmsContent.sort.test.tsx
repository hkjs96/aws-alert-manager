import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToastProvider } from "@/components/shared/Toast";
import { AlarmsContent } from "../AlarmsContent";
import type { Alarm } from "@/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/hooks/useOwnedCustomers", () => ({
  useOwnedCustomers: () => ({
    // 담당 고객사가 비면 OwnedEmptyState가 렌더된다 — 계정 111이 속한 cust-1을 소유한 상태로 둔다
    ownedCustomerIds: ["cust-1"],
    isLoading: false,
    toggleOwned: vi.fn(),
    isOwned: vi.fn(),
  }),
}));

vi.mock("@/lib/api-functions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  syncAlarms: vi.fn(),
}));

function alarm(id: string, state: Alarm["state"]): Alarm {
  return {
    id, alarm_name: id, arn: `arn:aws:cloudwatch:us-east-1:111:alarm:${id}`,
    account: "111", resource: `res-${id}`, type: "EC2", metric: "CPUUtilization",
    state, time: "2026-05-26T00:00:00Z", value: null,
  } as Alarm;
}

describe("AlarmsContent sorts the whole filtered set before paginating", () => {
  it("clicking the State header brings an ALARM from page 2 onto page 1", () => {
    // 25개(기본 페이지 크기)는 OK, 26번째(2페이지)만 ALARM. 시각이 같아 기본 정렬은 원래 순서 유지.
    const alarms = [
      ...Array.from({ length: 25 }, (_, i) => alarm(`ok-${String(i).padStart(2, "0")}`, "OK")),
      alarm("z-alarm", "ALARM"),
    ];

    render(
      <ToastProvider>
        <AlarmsContent
          alarms={alarms}
          summary={{ total: 26, alarm_count: 1, ok_count: 25, insufficient_count: 0 }}
          customers={[]}
          accounts={[{ id: "111", name: "Account", customerId: "cust-1" }]}
        />
      </ToastProvider>,
    );

    // 정렬 전: ALARM 행은 2페이지에 있어 보이지 않는다
    expect(screen.queryByText("res-z-alarm")).not.toBeInTheDocument();
    expect(screen.getByText("res-ok-00")).toBeInTheDocument();

    // 테이블 내부 정렬이었다면 현재 페이지 25개만 정렬돼 ALARM 행은 계속 2페이지에 남는다
    fireEvent.click(screen.getByText("State"));

    expect(screen.getByText("res-z-alarm")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("res-z-alarm");
  });
});
