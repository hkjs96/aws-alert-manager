'use client';

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { ToastProvider, useToast } from '../Toast';

// useToast를 호출하는 테스트용 컴포넌트
function TestTrigger({ variant, message, duration }: {
  variant: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
}) {
  const { showToast } = useToast();
  return (
    <button onClick={() => showToast(variant, message, duration)}>
      트리거
    </button>
  );
}

describe('Toast 알림 시스템', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('ToastProvider 없이 useToast 호출 시 에러를 던진다', () => {
    function BadComponent() {
      useToast();
      return null;
    }
    expect(() => render(<BadComponent />)).toThrow();
  });

  it('showToast 호출 시 토스트 메시지가 렌더링된다', () => {
    render(
      <ToastProvider>
        <TestTrigger variant="success" message="저장 완료" />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거'));
    expect(screen.getByText('저장 완료')).toBeInTheDocument();
  });

  it('5초 후 토스트가 자동으로 사라진다', () => {
    render(
      <ToastProvider>
        <TestTrigger variant="info" message="자동 dismiss 테스트" />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거'));
    expect(screen.getByText('자동 dismiss 테스트')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.queryByText('자동 dismiss 테스트')).not.toBeInTheDocument();
  });

  it('커스텀 duration으로 자동 dismiss 시간을 변경할 수 있다', () => {
    render(
      <ToastProvider>
        <TestTrigger variant="warning" message="커스텀 타이머" duration={2000} />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거'));
    expect(screen.getByText('커스텀 타이머')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.queryByText('커스텀 타이머')).not.toBeInTheDocument();
  });

  it('X 버튼 클릭으로 토스트를 수동 dismiss 할 수 있다', () => {
    render(
      <ToastProvider>
        <TestTrigger variant="error" message="수동 dismiss 테스트" />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거'));
    expect(screen.getByText('수동 dismiss 테스트')).toBeInTheDocument();

    const closeButton = screen.getByRole('button', { name: /닫기/i });
    fireEvent.click(closeButton);

    expect(screen.queryByText('수동 dismiss 테스트')).not.toBeInTheDocument();
  });

  it('여러 토스트가 동시에 스택으로 렌더링된다', () => {
    function MultiTrigger() {
      const { showToast } = useToast();
      return (
        <>
          <button onClick={() => showToast('success', '첫 번째')}>트리거1</button>
          <button onClick={() => showToast('error', '두 번째')}>트리거2</button>
        </>
      );
    }

    render(
      <ToastProvider>
        <MultiTrigger />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거1'));
    fireEvent.click(screen.getByText('트리거2'));

    expect(screen.getByText('첫 번째')).toBeInTheDocument();
    expect(screen.getByText('두 번째')).toBeInTheDocument();
  });

  it('토스트 컨테이너가 fixed top-right 위치에 렌더링된다', () => {
    render(
      <ToastProvider>
        <TestTrigger variant="info" message="위치 테스트" />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText('트리거'));

    const container = screen.getByTestId('toast-container');
    expect(container.className).toContain('fixed');
    expect(container.className).toContain('top-4');
    expect(container.className).toContain('right-4');
    expect(container.className).toContain('z-[100]');
  });

  describe('변형별 스타일', () => {
    it.each([
      ['success', 'border-green-600'],
      ['error', 'border-red-600'],
      ['warning', 'border-amber-600'],
      ['info', 'border-blue-600'],
    ] as const)('%s 변형은 %s 클래스를 포함한다', (variant, expectedClass) => {
      render(
        <ToastProvider>
          <TestTrigger variant={variant} message={`${variant} 테스트`} />
        </ToastProvider>
      );

      fireEvent.click(screen.getByText('트리거'));

      const toast = screen.getByText(`${variant} 테스트`).closest('[data-testid="toast-item"]');
      expect(toast?.className).toContain(expectedClass);
    });
  });
});
