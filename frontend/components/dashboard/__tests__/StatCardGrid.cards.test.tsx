import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatCardGrid } from "../StatCardGrid";

const stats = {
  monitored_count: 4, unmonitored_count: 296, active_alarms: 2, account_count: 1,
  active_alarms_ours: 0, active_alarms_customer: 2, accounts_connected: 1, accounts_failed: 0,
};

describe("StatCardGrid — 카드는 목록으로 가는 링크", () => {
  it("고객사 필터를 실어 각 목록으로 보낸다", () => {
    render(<StatCardGrid stats={stats} filters={{ customer_id: "HOME" }} />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      "/resources?monitoring=on&customer=HOME",
      "/alarms?state=ALARM&customer=HOME",
      "/resources?monitoring=off&customer=HOME",
      "/customers?customer=HOME",
    ]);
  });

  it("고객이 만든 알람도 세고 출처를 나눠 보여 준다", () => {
    render(<StatCardGrid stats={stats} />);
    expect(screen.getByText("우리 0 · 고객 2")).toBeInTheDocument();
    expect(screen.getByText("리소스 300개 중")).toBeInTheDocument();
    expect(screen.getByText("연결 1 · 실패 0")).toBeInTheDocument();
  });

  it("고객 알람 조회가 실패하면 All clear라고 하지 않는다", () => {
    render(<StatCardGrid stats={{ ...stats, active_alarms: 0, active_alarms_customer: null }} />);
    expect(screen.queryByText("All clear")).not.toBeInTheDocument();
    expect(screen.getByText("고객 알람 확인 불가")).toBeInTheDocument();
  });

  it("필터가 걸려 있으면 지난 방문 대비를 숨긴다", () => {
    const prev = { ...stats, account_count: 2 };
    const { rerender } = render(<StatCardGrid stats={stats} prevStats={prev} />);
    expect(screen.getAllByText(/No change|from last visit/).length).toBeGreaterThan(0);
    rerender(<StatCardGrid stats={stats} prevStats={prev} filters={{ customer_id: "HOME" }} />);
    expect(screen.queryByText(/No change|from last visit/)).not.toBeInTheDocument();
  });
});
