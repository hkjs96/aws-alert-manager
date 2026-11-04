import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricConfigStep } from "../MetricConfigStep";
import type { MetricRow } from "@/components/resources/MetricConfigSection";

const noop = vi.fn();

function makeMetric(name: string, enabled = true): MetricRow {
  return { key: name, name, threshold: 80, unit: "%", direction: ">", enabled };
}

const defaultProps = {
  metrics: [] as MetricRow[],
  setMetrics: noop as React.Dispatch<React.SetStateAction<MetricRow[]>>,
  customMetrics: [] as MetricRow[],
  setCustomMetrics: noop as React.Dispatch<React.SetStateAction<MetricRow[]>>,
  showCustom: false,
  setShowCustom: noop,
  selectedCwMetric: "",
  setSelectedCwMetric: noop,
  customThreshold: 0,
  setCustomThreshold: noop,
  customUnit: "",
  setCustomUnit: noop,
};

describe("MetricConfigStep 컴포넌트", () => {
  describe("트랙 1 (커스텀 알람 추가)", () => {
    it("CW 메트릭이 있는 리소스 타입이면 드롭다운 셀렉트를 렌더링한다", () => {
      render(<MetricConfigStep {...defaultProps} track={1} resourceType="EC2" />);
      // 커스텀 메트릭 설정 헤더
      expect(screen.getByText("Custom Metric Settings")).toBeInTheDocument();
      // 드롭다운 레이블
      expect(screen.getByText("Select CloudWatch Metric")).toBeInTheDocument();
    });

    it("CW 메트릭이 없는 리소스 타입이면 안내 메시지를 표시한다", () => {
      render(<MetricConfigStep {...defaultProps} track={1} resourceType="S3" />);
      expect(screen.getByText(/No additional CloudWatch metrics are available/)).toBeInTheDocument();
    });

    it("알 수 없는 리소스 타입이면 안내 메시지를 표시한다", () => {
      render(<MetricConfigStep {...defaultProps} track={1} resourceType="UNKNOWN_TYPE" />);
      expect(screen.getByText(/No additional CloudWatch metrics are available/)).toBeInTheDocument();
    });

    it("기본 메트릭 테이블(MetricConfigSection)을 렌더링하지 않는다", () => {
      render(
        <MetricConfigStep {...defaultProps} track={1} resourceType="EC2"
          metrics={[makeMetric("CPUUtilization")]}
        />,
      );
      // track 1이면 메트릭 설정 헤더(트랙 2용)가 없어야 함
      expect(screen.queryByText("Metric Settings")).not.toBeInTheDocument();
    });
  });

  describe("트랙 2 (새 모니터링 설정)", () => {
    it("메트릭 설정 헤더를 렌더링한다", () => {
      render(
        <MetricConfigStep {...defaultProps} track={2} resourceType="EC2"
          metrics={[makeMetric("CPUUtilization")]}
        />,
      );
      expect(screen.getByText("Metric Settings")).toBeInTheDocument();
    });

    it("트랙 1의 커스텀 메트릭 설정 헤더가 없다", () => {
      render(
        <MetricConfigStep {...defaultProps} track={2} resourceType="EC2"
          metrics={[makeMetric("CPUUtilization")]}
        />,
      );
      expect(screen.queryByText("Custom Metric Settings")).not.toBeInTheDocument();
    });
  });
});
