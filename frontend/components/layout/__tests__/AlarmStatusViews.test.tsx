import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlarmBadgeView, AlarmBellView } from "../AlarmStatusViews";
import { summarizeAlarms, ALARM_BELL_LIMIT } from "@/lib/alarm-status";
import type { Alarm } from "@/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function alarm(id: string, state: Alarm["state"]): Alarm {
  return {
    id, arn: `arn:${id}`, account: "111", resource: `res-${id}`,
    type: "EC2", metric: "CPUUtilization", state, time: "2026-05-26T00:00:00Z", value: null,
  };
}

describe("summarizeAlarms", () => {
  it("counts only ALARM state and caps the bell list", () => {
    const alarms = [
      ...Array.from({ length: ALARM_BELL_LIMIT + 5 }, (_, i) => alarm(`a${i}`, "ALARM")),
      alarm("ok", "OK"),
      alarm("ins", "INSUFFICIENT_DATA"),
    ];
    const summary = summarizeAlarms(alarms);
    expect(summary.count).toBe(ALARM_BELL_LIMIT + 5);
    expect(summary.alarming).toHaveLength(ALARM_BELL_LIMIT);
    // 클라이언트로 내려가는 DTO는 3개 필드뿐 (전체 레코드 아님)
    expect(Object.keys(summary.alarming[0]!).sort()).toEqual(["metric", "resource", "type"]);
  });
});

describe("AlarmBadgeView", () => {
  it("shows the ALARM count when firing", () => {
    render(<AlarmBadgeView count={3} />);
    expect(screen.getByText("ALARM 3")).toBeInTheDocument();
  });
  it("shows All clear when nothing fires", () => {
    render(<AlarmBadgeView count={0} />);
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });
});

describe("AlarmBellView", () => {
  it("opens the dropdown and lists firing alarms with resource links", () => {
    render(
      <AlarmBellView
        count={12}
        alarming={[{ resource: "i-001", metric: "CPUUtilization", type: "EC2" }]}
      />,
    );
    expect(screen.getByText("9+")).toBeInTheDocument(); // 9 초과 → 9+
    fireEvent.click(screen.getByLabelText("알림"));
    expect(screen.getByText("12 ALARM")).toBeInTheDocument();
    expect(screen.getByText("i-001")).toBeInTheDocument();
    expect(screen.getByText("i-001").closest("a")).toHaveAttribute("href", expect.stringContaining("/resources/"));
  });

  it("shows the empty message when nothing fires", () => {
    render(<AlarmBellView count={0} alarming={[]} />);
    fireEvent.click(screen.getByLabelText("알림"));
    expect(screen.getByText("현재 ALARM 상태인 알람이 없습니다")).toBeInTheDocument();
  });
});
