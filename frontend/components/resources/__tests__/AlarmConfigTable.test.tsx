import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ToastProvider } from "@/components/shared/Toast";
import { AlarmConfigTable } from "../AlarmConfigTable";
import type { AlarmConfig } from "@/types";

vi.mock("@/lib/api-functions", () => ({
  saveAlarmConfigs: vi.fn(),
}));

import { saveAlarmConfigs } from "@/lib/api-functions";

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

function renderTable(configs: AlarmConfig[] = [MOCK_CONFIG]) {
  return render(
    createElement(
      ToastProvider,
      null,
      createElement(AlarmConfigTable, {
        resourceId: "i-test",
        initialConfigs: configs,
        onAddCustomMetric: vi.fn(),
      }),
    ),
  );
}

describe("AlarmConfigTable — 미저장 변경 감지", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("초기 상태에서 unsaved indicator가 표시되지 않는다", () => {
    renderTable();
    expect(screen.queryByTitle("Unsaved changes")).not.toBeInTheDocument();
  });

  it("임계치 변경 시 unsaved indicator가 표시된다", () => {
    renderTable();
    const input = screen.getByDisplayValue("80");
    fireEvent.change(input, { target: { value: "90" } });
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();
  });

  it("Save Changes 버튼이 변경 없을 때 disabled이다", () => {
    renderTable();
    const saveBtn = screen.getByText("Save Changes");
    expect(saveBtn).toBeDisabled();
  });

  it("임계치 변경 후 Save Changes 버튼이 활성화된다", () => {
    renderTable();
    const input = screen.getByDisplayValue("80");
    fireEvent.change(input, { target: { value: "90" } });
    const saveBtn = screen.getByText("Save Changes");
    expect(saveBtn).not.toBeDisabled();
  });
});

describe("AlarmConfigTable — 기본값 리셋", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Reset to Defaults 클릭 시 임계치가 초기값으로 복원된다", () => {
    renderTable();

    const input = screen.getByDisplayValue("80");
    fireEvent.change(input, { target: { value: "95" } });
    expect(screen.getByDisplayValue("95")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Reset to Defaults"));

    expect(screen.getByDisplayValue("80")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("95")).not.toBeInTheDocument();
  });

  it("Reset to Defaults 후 unsaved indicator가 사라진다", () => {
    renderTable();

    const input = screen.getByDisplayValue("80");
    fireEvent.change(input, { target: { value: "90" } });
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Reset to Defaults"));
    expect(screen.queryByTitle("Unsaved changes")).not.toBeInTheDocument();
  });

  it("Reset to Defaults 후 Save Changes 버튼이 다시 disabled된다", () => {
    renderTable();

    const input = screen.getByDisplayValue("80");
    fireEvent.change(input, { target: { value: "90" } });
    fireEvent.click(screen.getByText("Reset to Defaults"));

    expect(screen.getByText("Save Changes")).toBeDisabled();
  });
});

describe("AlarmConfigTable — Unit/Direction/Severity 편집", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Unit 드롭다운 변경 시 dirty 상태가 된다", () => {
    renderTable();
    const selects = screen.getAllByRole("combobox");
    const unitSelect = selects[0];
    fireEvent.change(unitSelect, { target: { value: "Count" } });
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();
  });

  it("Direction 드롭다운 변경 시 dirty 상태가 된다", () => {
    renderTable();
    const selects = screen.getAllByRole("combobox");
    const dirSelect = selects[1];
    fireEvent.change(dirSelect, { target: { value: "<" } });
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();
  });

  it("Severity 드롭다운 변경 시 dirty 상태가 된다", () => {
    renderTable();
    const selects = screen.getAllByRole("combobox");
    const sevSelect = selects[2];
    fireEvent.change(sevSelect, { target: { value: "SEV-1" } });
    expect(screen.getByTitle("Unsaved changes")).toBeInTheDocument();
  });
});
