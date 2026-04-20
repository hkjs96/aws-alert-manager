import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ToastProvider } from "@/components/shared/Toast";
import { useMonitoringToggle } from "../useMonitoringToggle";

// toggleMonitoring mock
vi.mock("@/lib/api-functions", () => ({
  toggleMonitoring: vi.fn(),
}));

import { toggleMonitoring } from "@/lib/api-functions";

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(ToastProvider, null, children);

describe("useMonitoringToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("토글 성공 시 true를 반환한다", async () => {
    vi.mocked(toggleMonitoring).mockResolvedValue({
      job_id: "j1", status: "completed", total_count: 1,
      completed_count: 1, failed_count: 0, results: [],
    });

    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.toggle("res-1", true);
    });

    expect(success).toBe(true);
    expect(toggleMonitoring).toHaveBeenCalledWith("res-1", false);
  });

  it("토글 실패 시 false를 반환한다 (롤백 시그널)", async () => {
    vi.mocked(toggleMonitoring).mockRejectedValue(new Error("API error"));

    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });

    let success: boolean = true;
    await act(async () => {
      success = await result.current.toggle("res-2", false);
    });

    expect(success).toBe(false);
  });

  it("토글 진행 중 loadingIds에 리소스 ID가 포함된다", async () => {
    let resolveToggle: () => void;
    vi.mocked(toggleMonitoring).mockImplementation(
      () => new Promise<never>((resolve) => { resolveToggle = resolve as () => void; }),
    );

    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });

    act(() => {
      result.current.toggle("res-3", true);
    });

    expect(result.current.loadingIds.has("res-3")).toBe(true);
  });

  it("토글 완료 후 loadingIds에서 리소스 ID가 제거된다", async () => {
    vi.mocked(toggleMonitoring).mockResolvedValue({
      job_id: "j2", status: "completed", total_count: 1,
      completed_count: 1, failed_count: 0, results: [],
    });

    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });

    await act(async () => {
      await result.current.toggle("res-4", true);
    });

    expect(result.current.loadingIds.has("res-4")).toBe(false);
  });

  it("토글 실패 후에도 loadingIds에서 리소스 ID가 제거된다", async () => {
    vi.mocked(toggleMonitoring).mockRejectedValue(new Error("fail"));

    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });

    await act(async () => {
      await result.current.toggle("res-5", false);
    });

    expect(result.current.loadingIds.has("res-5")).toBe(false);
  });
});
