import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { createElement } from "react";
import { ToastProvider } from "@/components/shared/Toast";
import { AlarmConfigTable } from "../AlarmConfigTable";
import type { AlarmConfig } from "@/types";

const MOCK_CONFIG: AlarmConfig = {
  metric_key: "CPU",
  metric_name: "CPUUtilization",
  namespace: "AWS/EC2",
  threshold: 80,
  unit: "Percent",
  direction: ">",
  severity: "SEV-3",
  source: "System",
  state: "OK",
  current_value: 45,
  monitoring: true,
};

function renderTable(configs: AlarmConfig[] = [MOCK_CONFIG], onEdit = vi.fn()) {
  render(
    createElement(
      ToastProvider,
      null,
      createElement(AlarmConfigTable, {
        resourceId: "i-test",
        initialConfigs: configs,
        onAddAlarm: vi.fn(),
        onEdit,
      }),
    ),
  );
  return onEdit;
}

// 편집은 "알람 편집" 창(PUT /thresholds)으로 옮겼다 — 표는 지금 알람을 보여주기만 한다(2026-11-03).
describe("AlarmConfigTable — 읽기 전용", () => {
  it("값을 바꿀 수 없고 저장 버튼이 없다", () => {
    renderTable();
    expect(screen.getByDisplayValue("80")).toBeDisabled();
    expect(screen.queryByText("Save Changes")).not.toBeInTheDocument();
    expect(screen.queryByText("Reset to Defaults")).not.toBeInTheDocument();
  });

  it("알람 편집 버튼이 편집 창을 연다", () => {
    const onEdit = renderTable();
    fireEvent.click(screen.getByText("Edit Alarms"));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("디스크 경로를 보여준다", () => {
    renderTable([{ ...MOCK_CONFIG, metric_key: "disk_used_percent:/data", metric_name: "disk_used_percent", mount_path: "/data" }]);
    expect(screen.getByText("/data")).toBeInTheDocument();
  });
});
