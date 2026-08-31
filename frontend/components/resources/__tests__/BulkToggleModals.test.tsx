import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { EnableModal } from "../EnableModal";
import { DisableModal } from "../DisableModal";

const showToast = vi.fn();
vi.mock("@/components/shared/Toast", () => ({ useToast: () => ({ showToast }) }));

const toggleMonitoring = vi.fn();
vi.mock("@/lib/api-functions", () => ({
  toggleMonitoring: (...args: unknown[]) => toggleMonitoring(...args),
}));

beforeEach(() => {
  showToast.mockReset();
  toggleMonitoring.mockReset();
});

describe("EnableModal", () => {
  it("calls the per-resource monitoring PUT for every selected id and reports success", async () => {
    toggleMonitoring.mockResolvedValue({});
    const onComplete = vi.fn();
    render(
      <EnableModal selectedIds={["i-1", "i-2"]} selectedType="EC2" isSameType onClose={vi.fn()} onComplete={onComplete} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "활성화" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(expect.arrayContaining(["i-1", "i-2"])));
    expect(toggleMonitoring).toHaveBeenCalledWith("i-1", true);
    expect(toggleMonitoring).toHaveBeenCalledWith("i-2", true);
    expect(showToast).toHaveBeenCalledWith("success", "2개 리소스의 모니터링을 활성화했습니다.");
  });

  it("reports partial failure and only completes the succeeded ids", async () => {
    toggleMonitoring.mockImplementation(async (id: string) => {
      if (id === "i-2") throw new Error("AWS_ERROR");
      return {};
    });
    const onComplete = vi.fn();
    render(
      <EnableModal selectedIds={["i-1", "i-2"]} selectedType={null} isSameType={false} onClose={vi.fn()} onComplete={onComplete} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "활성화" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(["i-1"]));
    expect(showToast).toHaveBeenCalledWith("error", expect.stringContaining("1개 활성화, 1개 실패: i-2"));
  });

  it("keeps the modal actionable when everything fails", async () => {
    toggleMonitoring.mockRejectedValue(new Error("down"));
    const onComplete = vi.fn();
    render(
      <EnableModal selectedIds={["i-1"]} selectedType="EC2" isSameType onClose={vi.fn()} onComplete={onComplete} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "활성화" }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith("error", "모니터링 활성화에 실패했습니다 (1개)."));
    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "활성화" })).toBeInTheDocument();
  });
});

describe("DisableModal", () => {
  it("disables monitoring per resource and completes with the succeeded ids", async () => {
    toggleMonitoring.mockResolvedValue({});
    const onComplete = vi.fn();
    render(<DisableModal selectedIds={["db-1"]} onClose={vi.fn()} onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: "비활성화" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(["db-1"]));
    expect(toggleMonitoring).toHaveBeenCalledWith("db-1", false);
    expect(showToast).toHaveBeenCalledWith("success", "1개 리소스의 모니터링을 비활성화했습니다.");
  });
});
