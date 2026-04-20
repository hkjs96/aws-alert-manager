import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { SourceBadge } from '../SourceBadge';
import type { SourceType } from '@/types';

describe('SourceBadge', () => {
  it('System 뱃지에 회색 배경을 렌더링한다', () => {
    render(<SourceBadge source="System" />);
    const badge = screen.getByText('System');
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain('bg-gray-100');
    expect(badge.className).toContain('text-gray-700');
  });

  it('Customer 뱃지에 파란색 배경을 렌더링한다', () => {
    render(<SourceBadge source="Customer" />);
    const badge = screen.getByText('Customer');
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain('bg-blue-100');
    expect(badge.className).toContain('text-blue-700');
  });

  it('Custom 뱃지에 보라색 배경을 렌더링한다', () => {
    render(<SourceBadge source="Custom" />);
    const badge = screen.getByText('Custom');
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain('bg-purple-100');
    expect(badge.className).toContain('text-purple-700');
  });
});
