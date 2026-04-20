import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ToastProvider } from "@/components/shared/Toast";
import { AlarmConfigTable } from "../AlarmConfigTable";
import { ResourceEvents } from "../ResourceEvents";
import { ResourceHeader } from "../ResourceHeader";
import type { AlarmConfig, RecentAlarm, Resource } from "@/types";

// Mock api-functions
vi.mock("@/lib/api-functions", () => ({
  saveAlarmConfigs: vi.fn().mockResolvedValue({ job_id: "j1", status: "completed", total_count: 1, completed_count: 1, failed_count: 0, results: [] }),
  toggleMonitoring: vi.fn().mockResolvedValue({ job_id: "j2", status: "completed", total_count: 1, completed_count: 1, failed_count: 0, results: [] }),
  fetchAvailableMetrics: vi.fn().mockResolvedValue([]),
}));

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/resources/test",
  useSearchParams: () => new URLSearchParams(),
}));

const MOCK_RESOURCE: Resource = {
  id: "i-0a2b4c6d8e0f12",
  name: "payments-api-prod-01",
  type: "EC2",
  account: "882311440092",
  region: "us-east-1",
  monitoring: true,
  alarms: { critical: 2, warning: 0 },
};

const MOCK_CONFIGS: AlarmConfig[] = [
  {
    metric_key: "CPU",
    metric_name: "CPUUtilization",
    namespace: "AWS/EC2",
    threshold: 80,
    unit: "%",
    direction: ">",
    severity: "SEV-3",
    source: "System",
    state: "OK",
    current_value: 48,
    monitoring: true,
  },
  {
    metric_key: "Memory",
    metric_name: "mem_used_percent",
    namespace: "CWAgent",
    threshold: 80,
    unit: "%",
    direction: ">",
    severity: "SEV-3",
    source: "System",
    state: "OK",
    current_value: 48,
    monitoring: true,
  },
];

const MOCK_EVENTS: RecentAlarm[] = [
  {
    timestamp: "2024-06-15T14:22:05Z",
    resource_id: "i-0a2b4c6d8e0f12",
    resource_name: "payments-api-prod-01",
    resource_type: "EC2",
    metric: "CPUUtilization",
    severity: "SEV-1",
    state_change: "OK → ALARM",
    value: 94.2,
    threshold: 85.0,
  },
];

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe("ResourceHeader", () => {
  it("리소스 이름과 메타데이터를 표시한다", () => {
    render(<ResourceHeader resource={MOCK_RESOURCE} />, { wrapper: Wrapper });
    expect(screen.getByText("payments-api-prod-01")).toBeInTheDocument();
    expect(screen.getByText("EC2")).toBeInTheDocument();
    expect(screen.getByText("882311440092")).toBeInTheDocument();
    expect(screen.getByText("us-east-1")).toBeInTheDocument();
  });

  it("모니터링 활성 상태를 표시한다", () => {
    render(<ResourceHeader resource={MOCK_RESOURCE} />, { wrapper: Wrapper });
    expect(screen.getByText("Monitoring On")).toBeInTheDocument();
  });

  it("Back to Resource Fleet 링크를 표시한다", () => {
    render(<ResourceHeader resource={MOCK_RESOURCE} />, { wrapper: Wrapper });
    const link = screen.getByText("Back to Resource Fleet");
    expect(link.closest("a")).toHaveAttribute("href", "/resources");
  });
});

describe("AlarmConfigTable", () => {
  it("알람 설정 행을 렌더링한다", () => {
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText("CPUUtilization")).toBeInTheDocument();
    expect(screen.getByText("mem_used_percent")).toBeInTheDocument();
  });

  it("임계치 수정 시 unsaved indicator를 표시한다", () => {
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );
    // Initially no unsaved indicator
    expect(screen.queryByTitle("Unsaved changes")).not.toBeInTheDocument();

    // Change a threshold
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "90" } });

    // Now unsaved indicator should appear
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();
  });

  it("Save Changes 버튼이 변경 없을 때 비활성화된다", () => {
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText("Save Changes").closest("button")).toBeDisabled();
  });

  it("Save Changes 클릭 시 API를 호출하고 성공 토스트를 표시한다", async () => {
    const { saveAlarmConfigs } = await import("@/lib/api-functions");
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );

    // Make a change
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "90" } });

    // Click save
    fireEvent.click(screen.getByText("Save Changes"));

    await waitFor(() => {
      expect(saveAlarmConfigs).toHaveBeenCalled();
    });
  });

  it("Reset to Defaults 클릭 시 원래 값으로 복원한다", () => {
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );

    // Change a threshold
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "90" } });
    expect((inputs[0] as HTMLInputElement).value).toBe("90");

    // Reset
    fireEvent.click(screen.getByText("Reset to Defaults"));
    const resetInputs = screen.getAllByRole("spinbutton");
    expect((resetInputs[0] as HTMLInputElement).value).toBe("80");
  });

  it("SeverityBadge와 SourceBadge를 표시한다", () => {
    render(
      <AlarmConfigTable
        resourceId="i-0a2b4c6d8e0f12"
        initialConfigs={MOCK_CONFIGS}
        onAddCustomMetric={vi.fn()}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getAllByText("SEV-3")).toHaveLength(2);
    expect(screen.getAllByText("System")).toHaveLength(2);
  });
});

describe("ResourceEvents", () => {
  it("이벤트 목록을 타임라인 형식으로 표시한다", () => {
    render(<ResourceEvents events={MOCK_EVENTS} />);
    expect(screen.getByText("Recent Events")).toBeInTheDocument();
    expect(screen.getByText(/CPUUtilization/)).toBeInTheDocument();
  });

  it("이벤트가 없을 때 빈 메시지를 표시한다", () => {
    render(<ResourceEvents events={[]} />);
    expect(screen.getByText("No recent events.")).toBeInTheDocument();
  });
});
