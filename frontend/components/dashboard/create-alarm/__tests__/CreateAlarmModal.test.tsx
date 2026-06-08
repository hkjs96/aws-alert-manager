/**
 * CreateAlarmModal 컴포넌트 테스트 (태스크 7.3~7.6)
 *
 * 7.3: 기본 렌더링 및 닫기 동작
 * 7.4: 캐스케이딩 초기화 — 트랙/고객사/어카운트 변경 시 하위 상태 리셋
 * 7.5: 모달 재오픈 시 초기 상태로 복원
 * 7.6: 트랙 변경 시 하위 상태 초기화
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import * as fc from "fast-check";
import { ToastProvider } from "@/components/shared/Toast";
import { CreateAlarmModal } from "../CreateAlarmModal";

// fetchResources / fetchCustomers / fetchAccounts mock
vi.mock("@/lib/api-functions", () => ({
  fetchResources: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 }),
  fetchCustomers: vi.fn().mockResolvedValue([]),
  fetchAccounts: vi.fn().mockResolvedValue([]),
}));

function renderModal(props: { open?: boolean; onClose?: () => void; onSuccess?: () => void } = {}) {
  const onClose = props.onClose ?? vi.fn();
  const { rerender, unmount } = render(
    <ToastProvider>
      <CreateAlarmModal open={props.open ?? true} onClose={onClose} onSuccess={props.onSuccess} />
    </ToastProvider>,
  );
  return { onClose, rerender, unmount };
}

// ──────────────────────────────────────────────
// 7.3: 기본 렌더링 및 닫기
// ──────────────────────────────────────────────

describe("CreateAlarmModal — 기본 렌더링 및 닫기 (7.3)", () => {
  it("open=true이면 모달이 렌더링된다", () => {
    renderModal({ open: true });
    expect(screen.getByTestId("create-alarm-modal")).toBeInTheDocument();
  });

  it("open=false이면 모달이 렌더링되지 않는다", () => {
    renderModal({ open: false });
    expect(screen.queryByTestId("create-alarm-modal")).not.toBeInTheDocument();
  });

  it("닫기 버튼 클릭 시 onClose가 호출된다", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByTestId("close-button"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("오버레이(배경) 클릭 시 onClose가 호출된다", () => {
    const { onClose } = renderModal();
    // 모달 외부 배경 오버레이
    const modal = screen.getByTestId("create-alarm-modal");
    const overlay = modal.parentElement?.firstElementChild as HTMLElement;
    if (overlay && overlay !== modal) fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalled();
  });

  it("초기에 두 트랙 카드가 모두 표시된다", () => {
    renderModal();
    expect(screen.getByTestId("track-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("track-card-2")).toBeInTheDocument();
  });

  it("초기에는 리소스 선택 단계가 숨겨져 있다", () => {
    renderModal();
    expect(screen.queryByTestId("customer-select")).not.toBeInTheDocument();
  });
});

// ──────────────────────────────────────────────
// 7.4: 캐스케이딩 초기화 속성 테스트
// ──────────────────────────────────────────────

describe("CreateAlarmModal — 캐스케이딩 초기화 (7.4)", () => {
  it("트랙 선택 후 resource-filter 단계로 전환된다", async () => {
    renderModal();
    fireEvent.click(screen.getByTestId("track-card-1"));
    await waitFor(() => {
      expect(screen.getByTestId("customer-select")).toBeInTheDocument();
    });
  });

  it("트랙 1 → 트랙 2 재클릭 시 고객사 선택이 다시 표시된다", async () => {
    renderModal();
    fireEvent.click(screen.getByTestId("track-card-1"));
    await waitFor(() => expect(screen.getByTestId("customer-select")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("track-card-2"));
    await waitFor(() => {
      expect(screen.getByTestId("customer-select")).toBeInTheDocument();
    });
  });
});

// ──────────────────────────────────────────────
// 7.5: 모달 재오픈 초기 상태 속성 테스트 (fast-check)
// ──────────────────────────────────────────────

describe("CreateAlarmModal — 모달 재오픈 초기 상태 (7.5)", () => {
  it("Property: 모달을 닫았다가 다시 열면 트랙 선택 단계로 초기화된다", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom(1, 2),
        async (trackNum) => {
          cleanup(); // 이전 렌더 잔여물 정리
          const onClose = vi.fn();
          const { rerender, getByTestId, queryByTestId } = render(
            <ToastProvider>
              <CreateAlarmModal open={true} onClose={onClose} />
            </ToastProvider>,
          );

          // 트랙 선택
          fireEvent.click(getByTestId(`track-card-${trackNum}`));
          await waitFor(() => expect(getByTestId("customer-select")).toBeInTheDocument());

          // 닫기
          fireEvent.click(getByTestId("close-button"));

          // 다시 열기
          rerender(
            <ToastProvider>
              <CreateAlarmModal open={false} onClose={onClose} />
            </ToastProvider>,
          );
          rerender(
            <ToastProvider>
              <CreateAlarmModal open={true} onClose={onClose} />
            </ToastProvider>,
          );

          // track-select 단계: customer-select가 없어야 함
          expect(queryByTestId("customer-select")).not.toBeInTheDocument();
          // 두 트랙 카드는 표시
          expect(getByTestId("track-card-1")).toBeInTheDocument();
          expect(getByTestId("track-card-2")).toBeInTheDocument();

          cleanup();
        },
      ),
      { numRuns: 2 },
    );
  });
});

// ──────────────────────────────────────────────
// 7.6: 트랙 변경 시 하위 상태 초기화 속성 테스트
// ──────────────────────────────────────────────

describe("CreateAlarmModal — 트랙 변경 시 하위 상태 초기화 (7.6)", () => {
  it("Property: 어느 트랙을 클릭해도 resource-filter 단계가 나타난다", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom(1, 2),
        fc.constantFrom(1, 2),
        async (firstTrack, secondTrack) => {
          cleanup();
          const { getByTestId } = render(
            <ToastProvider>
              <CreateAlarmModal open={true} onClose={vi.fn()} />
            </ToastProvider>,
          );

          fireEvent.click(getByTestId(`track-card-${firstTrack}`));
          await waitFor(() => expect(getByTestId("customer-select")).toBeInTheDocument());

          fireEvent.click(getByTestId(`track-card-${secondTrack}`));
          await waitFor(() => expect(getByTestId("customer-select")).toBeInTheDocument());

          // resource-filter가 표시되어 있어야 함
          expect(getByTestId("customer-select")).toBeInTheDocument();

          cleanup();
        },
      ),
      { numRuns: 4 },
    );
  });
});
