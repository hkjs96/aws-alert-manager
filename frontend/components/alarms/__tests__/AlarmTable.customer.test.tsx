import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { AlarmTable } from "../AlarmTable";

const base = { time: "2026-10-20T00:00:00Z", account: "771283576189", metric: "NetworkIn", state: "ALARM" as const };

describe("AlarmTable — 고객 알람", () => {
  it("고객 알람 표시와 알람 이름을 보여 준다", () => {
    render(<AlarmTable alarms={[{ ...base, id: "a", arn: "arn:1", resource: "i-0abc", type: "EC2",
      source: "customer", alarm_name: "[EC2]WEBFIL_NetworkIn_over" }]} sortKey="time" sortDir="desc" onSort={() => {}} />);
    expect(screen.getByText("고객 알람")).toBeInTheDocument();
    expect(screen.getByText("[EC2]WEBFIL_NetworkIn_over")).toBeInTheDocument();
  });

  it("리소스를 모르는 고객 알람은 눌러도 이동하지 않는다", () => {
    render(<AlarmTable alarms={[{ ...base, id: "b", arn: "arn:2", resource: "", type: "",
      source: "customer", alarm_name: "TEST-ALARM" }]} sortKey="time" sortDir="desc" onSort={() => {}} />);
    fireEvent.click(screen.getByText("TEST-ALARM"));
    expect(push).not.toHaveBeenCalled();
  });
});
