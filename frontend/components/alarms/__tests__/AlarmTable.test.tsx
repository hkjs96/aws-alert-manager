import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AlarmTable, sortAlarms } from "../AlarmTable";
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

    render(<AlarmTable alarms={alarms} sortKey="time" sortDir="desc" onSort={() => {}} />);

    expect(screen.getByText("disk_used_percent")).toBeInTheDocument();
    expect(screen.getByText("/data")).toBeInTheDocument();
  });
});

function alarm(id: string, over: Partial<Alarm>): Alarm {
  return {
    id, alarm_name: id, arn: `arn:aws:cloudwatch:us-east-1:123:alarm:${id}`,
    account: "123", resource: `res-${id}`, type: "EC2", metric: "CPUUtilization",
    state: "OK", time: "2026-05-26T00:00:00Z", value: null,
    ...over,
  } as Alarm;
}

describe("AlarmTable header sort is controlled by the parent", () => {
  it("clicking a sortable header calls onSort with the column key and does not reorder locally", () => {
    const onSort = vi.fn();
    const alarms = [alarm("a", { state: "OK" }), alarm("b", { state: "ALARM" })];
    render(<AlarmTable alarms={alarms} sortKey="time" sortDir="desc" onSort={onSort} />);

    screen.getByText("State").click();
    expect(onSort).toHaveBeenCalledWith("state");
    // 렌더 순서는 넘겨받은 순서 그대로 (정렬은 부모가 페이지 슬라이스 전에 수행)
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("res-a");
    expect(rows[1]).toHaveTextContent("res-b");
  });
});

describe("sortAlarms", () => {
  const alarms = [
    alarm("ok", { state: "OK", time: "2026-05-26T02:00:00Z" }),
    alarm("alarm", { state: "ALARM", time: "2026-05-26T01:00:00Z" }),
    alarm("insufficient", { state: "INSUFFICIENT_DATA", time: "2026-05-26T03:00:00Z" }),
  ];

  it("orders by state severity (ALARM first) ascending", () => {
    expect(sortAlarms(alarms, "state", "asc").map((a) => a.id)).toEqual(["alarm", "insufficient", "ok"]);
  });

  it("orders by time descending", () => {
    expect(sortAlarms(alarms, "time", "desc").map((a) => a.id)).toEqual(["insufficient", "ok", "alarm"]);
  });

  it("does not mutate the input array", () => {
    const copy = [...alarms];
    sortAlarms(alarms, "state", "asc");
    expect(alarms).toEqual(copy);
  });
});
