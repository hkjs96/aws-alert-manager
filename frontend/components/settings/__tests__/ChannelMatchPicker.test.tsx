import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChannelMatchPicker, describeMatch } from "../ChannelMatchPicker";

const severities = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"];
const one = [{ id: "771283576189", name: "HOME-PRD", customerId: "HOME" }];
const two = [...one, { id: "222222222222", name: "HOME-DEV", customerId: "HOME" }];

describe("ChannelMatchPicker", () => {
  it("등급은 설명이 붙은 체크 목록이다", () => {
    const onChange = vi.fn();
    render(<ChannelMatchPicker match={{ severity: ["SEV-1", "SEV-3"] }} severities={severities}
      accounts={one} typeCounts={{}} onChange={onChange} />);
    expect(screen.getByText("서비스 장애 · 즉시")).toBeInTheDocument();
    const sev3 = screen.getByRole("checkbox", { name: /SEV-3/ });
    expect(sev3).toBeChecked();
    fireEvent.click(sev3);
    expect(onChange).toHaveBeenCalledWith({ severity: ["SEV-1"] });
  });

  it("타입은 기본이 전부 받기이고, 골라서 받기를 고르면 이 고객사에 있는 타입만 개수와 함께 보인다", () => {
    const onChange = vi.fn();
    render(<ChannelMatchPicker match={{}} severities={severities} accounts={one}
      typeCounts={{ EC2: 12, ALB: 3 }} onChange={onChange} />);
    expect(screen.queryByRole("button", { name: /EC2/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByLabelText("골라서 받기")[0]!);
    expect(screen.getByText(/이대로 저장하면 전부 받습니다/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "EC2 12" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "RDS" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /모든 타입 보기/ }));
    expect(screen.getByRole("button", { name: "RDS" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "EC2 12" }));
    expect(onChange).toHaveBeenLastCalledWith({ resource_type: ["EC2"] });
  });

  it("전부 받기로 돌아가면 고른 값을 비운다", () => {
    const onChange = vi.fn();
    render(<ChannelMatchPicker match={{ resource_type: ["EC2"] }} severities={severities} accounts={one}
      typeCounts={{ EC2: 1 }} onChange={onChange} />);
    fireEvent.click(screen.getAllByLabelText("전부 받기")[0]!);
    expect(onChange).toHaveBeenLastCalledWith({ resource_type: [] });
  });

  it("계정이 하나면 계정 조건을 숨기고, 둘 이상이면 보여 준다", () => {
    const { rerender } = render(<ChannelMatchPicker match={{}} severities={severities} accounts={one}
      typeCounts={{}} onChange={vi.fn()} />);
    expect(screen.queryByText("계정")).not.toBeInTheDocument();
    rerender(<ChannelMatchPicker match={{}} severities={severities} accounts={two}
      typeCounts={{}} onChange={vi.fn()} />);
    expect(screen.getByText("계정")).toBeInTheDocument();
  });
});

describe("describeMatch", () => {
  it("저장하면 무엇을 받는지 한 줄로", () => {
    expect(describeMatch({ severity: ["SEV-1", "SEV-2", "SEV-3"] }, "HOME"))
      .toBe("HOME의 SEV-1·SEV-2·SEV-3 알림을 모든 리소스에서 받습니다.");
    expect(describeMatch({ resource_type: ["EC2"], account_id: ["1"] }, ""))
      .toBe("모든 고객사의 모든 등급 알림을 EC2에서 받습니다 (계정 1개).");
  });
});
