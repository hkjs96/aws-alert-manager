import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AlarmTable } from "../AlarmTable";
import type { Alarm } from "@/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe("AlarmTable", () => {
  it("shows disk mount path below disk metrics", () => {
    const alarms: Alarm[] = [{
      id: "alarm-1",
      alarm_name: "alarm-1",
      arn: "arn:aws:cloudwatch:us-east-1:123:alarm:alarm-1",
      account: "123",
      resource: "i-001",
      type: "EC2",
      metric: "disk_used_percent",
      mount_path: "/data",
      state: "OK",
      time: "2026-05-26T00:00:00Z",
      value: null,
    } as Alarm];

    render(<AlarmTable alarms={alarms} />);

    expect(screen.getByText("disk_used_percent")).toBeInTheDocument();
    expect(screen.getByText("/data")).toBeInTheDocument();
  });
});
