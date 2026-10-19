import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ToastProvider } from "@/components/shared/Toast";
import { useMonitoringToggle } from "../useMonitoringToggle";

// toggleMonitoring mock
vi.mock("@/lib/api-functions", () => ({
  toggleMonitoring: vi.fn(),
  fetchAlarmOverlaps: vi.fn(async () => ({ resource_id: "", region: "", overlaps: [] })),
}));

import { fetchAlarmOverlaps, toggleMonitoring } from "@/lib/api-functions";

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
    // 토글이 진행 중(pending) 상태로 머무르도록 resolve 하지 않는 Promise 반환
    vi.mocked(toggleMonitoring).mockImplementation(
      () => new Promise<never>(() => {}),
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

describe("useMonitoringToggle — 켜기 전 중복 점검", () => {
  const DONE = { job_id: "j", status: "completed", total_count: 1, completed_count: 1, failed_count: 0, results: [] } as never;
  const OVERLAP = {
    resource_id: "i-1", region: "ap-northeast-2",
    overlaps: [{ metric: "StatusCheckFailed", namespace: "AWS/EC2", metric_name: "StatusCheckFailed",
      customer_alarms: [{ name: "[EC2]BASTION STATUS_CHECK_FAILED" }] }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(toggleMonitoring).mockResolvedValue(DONE);
  });

  it("겹치는 고객 알람이 있으면 확인을 받고, 취소하면 켜지 않는다", async () => {
    vi.mocked(fetchAlarmOverlaps).mockResolvedValue(OVERLAP);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });
    let success = true;
    await act(async () => { success = await result.current.toggle("i-1", false); });
    expect(confirm.mock.calls[0]?.[0]).toContain("[EC2]BASTION STATUS_CHECK_FAILED");
    expect(success).toBe(false);
    expect(toggleMonitoring).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("확인하면 켠다", async () => {
    vi.mocked(fetchAlarmOverlaps).mockResolvedValue(OVERLAP);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });
    await act(async () => { await result.current.toggle("i-1", false); });
    expect(toggleMonitoring).toHaveBeenCalledWith("i-1", true);
    confirm.mockRestore();
  });

  it("끌 때와 점검 실패 시에는 묻지 않는다", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const { result } = renderHook(() => useMonitoringToggle(), { wrapper });
    await act(async () => { await result.current.toggle("i-1", true); });
    expect(fetchAlarmOverlaps).not.toHaveBeenCalled();
    vi.mocked(fetchAlarmOverlaps).mockRejectedValue(new Error("502"));
    await act(async () => { await result.current.toggle("i-1", false); });
    expect(confirm).not.toHaveBeenCalled();
    expect(toggleMonitoring).toHaveBeenLastCalledWith("i-1", true);
    confirm.mockRestore();
  });
});
