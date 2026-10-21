import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/components/shared/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api-functions", () => ({
  previewChannel: vi.fn(async () => ({
    days: 30, messages: 30, per_day: 1, events: 40, events_total: 253, by_severity: { "SEV-2": 30, "SEV-3": 10 },
  })),
}));

import { previewChannel } from "@/lib/api-functions";
import { PreviewLine } from "../NotificationSection";

describe("PreviewLine — 저장 전 예상 건수", () => {
  it("지난 30일 기준 건수와 하루 평균을 보여 준다", async () => {
    render(<PreviewLine customerId="HOME" match={{ severity: ["SEV-1", "SEV-2", "SEV-3"], resource_type: [] }} />);
    await waitFor(() => expect(screen.getByText("30건")).toBeInTheDocument(), { timeout: 2000 });
    expect(screen.getByText(/하루 약 1건/)).toBeInTheDocument();
    // 빈 축은 보내지 않는다(= 전부)
    expect(previewChannel).toHaveBeenCalledWith({ customer_id: "HOME", match: { severity: ["SEV-1", "SEV-2", "SEV-3"] } });
  });
});
