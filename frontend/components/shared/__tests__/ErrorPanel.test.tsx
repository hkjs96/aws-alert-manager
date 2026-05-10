import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ErrorPanel } from '../ErrorPanel';

describe('ErrorPanel', () => {
  it('에러 메시지를 렌더링한다', () => {
    render(<ErrorPanel message="서버 오류가 발생했습니다" onRetry={() => {}} />);
    expect(screen.getByText('서버 오류가 발생했습니다')).toBeInTheDocument();
  });

  it('data-testid="error-panel"이 루트에 존재한다', () => {
    render(<ErrorPanel message="에러" onRetry={() => {}} />);
    expect(screen.getByTestId('error-panel')).toBeInTheDocument();
  });

  it('"다시 시도" 버튼을 렌더링한다', () => {
    render(<ErrorPanel message="에러" onRetry={() => {}} />);
    expect(screen.getByTestId('retry-button')).toBeInTheDocument();
    expect(screen.getByText('다시 시도')).toBeInTheDocument();
  });

  it('다시 시도 버튼 클릭 시 onRetry 콜백을 호출한다', () => {
    const onRetry = vi.fn();
    render(<ErrorPanel message="에러" onRetry={onRetry} />);
    fireEvent.click(screen.getByTestId('retry-button'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
