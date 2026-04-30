import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TrackSelector } from "../TrackSelector";

describe("TrackSelector 컴포넌트", () => {
  it("두 개의 트랙 카드를 렌더링한다", () => {
    render(<TrackSelector selectedTrack={null} onSelectTrack={vi.fn()} />);
    expect(screen.getByTestId("track-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("track-card-2")).toBeInTheDocument();
  });

  it("트랙 1 카드 클릭 시 onSelectTrack(1)이 호출된다", () => {
    const onSelect = vi.fn();
    render(<TrackSelector selectedTrack={null} onSelectTrack={onSelect} />);
    fireEvent.click(screen.getByTestId("track-card-1"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("트랙 2 카드 클릭 시 onSelectTrack(2)이 호출된다", () => {
    const onSelect = vi.fn();
    render(<TrackSelector selectedTrack={null} onSelectTrack={onSelect} />);
    fireEvent.click(screen.getByTestId("track-card-2"));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("선택된 트랙 카드에 border-primary 클래스가 적용된다", () => {
    render(<TrackSelector selectedTrack={1} onSelectTrack={vi.fn()} />);
    const card1 = screen.getByTestId("track-card-1");
    expect(card1.className).toContain("border-primary");
  });

  it("선택되지 않은 트랙 카드에 border-primary 클래스가 없다", () => {
    render(<TrackSelector selectedTrack={1} onSelectTrack={vi.fn()} />);
    const card2 = screen.getByTestId("track-card-2");
    expect(card2.className).not.toContain("border-primary");
  });

  it("selectedTrack이 null이면 어느 카드도 선택 스타일이 없다", () => {
    render(<TrackSelector selectedTrack={null} onSelectTrack={vi.fn()} />);
    expect(screen.getByTestId("track-card-1").className).not.toContain("border-primary");
    expect(screen.getByTestId("track-card-2").className).not.toContain("border-primary");
  });

  it("카드에 타이틀 텍스트가 렌더링된다", () => {
    render(<TrackSelector selectedTrack={null} onSelectTrack={vi.fn()} />);
    expect(screen.getByText("커스텀 알람 추가")).toBeInTheDocument();
    expect(screen.getByText("새 모니터링 설정")).toBeInTheDocument();
  });
});
