import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChannelMatchPicker } from "../ChannelMatchPicker";

const severities = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"];
const accounts = [{ id: "771283576189", name: "HOME-PRD", customerId: "HOME" }];

describe("ChannelMatchPicker", () => {
  it("선택된 값은 눌린 상태로 보이고, 누르면 빠진다", () => {
    const onChange = vi.fn();
    render(
      <ChannelMatchPicker match={{ severity: ["SEV-1", "SEV-3"] }} severities={severities}
        accounts={accounts} onChange={onChange} />,
    );
    expect(screen.getByRole("button", { name: "SEV-3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "SEV-4" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "SEV-3" }));
    expect(onChange).toHaveBeenCalledWith({ severity: ["SEV-1"] });
  });

  it("리소스 타입과 계정은 목록에서 고른다(손으로 치지 않는다)", () => {
    const onChange = vi.fn();
    render(<ChannelMatchPicker match={{}} severities={severities} accounts={accounts} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "EC2" }));
    expect(onChange).toHaveBeenLastCalledWith({ resource_type: ["EC2"] });
    fireEvent.click(screen.getByRole("button", { name: "HOME-PRD (771283576189)" }));
    expect(onChange).toHaveBeenLastCalledWith({ account_id: ["771283576189"] });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
