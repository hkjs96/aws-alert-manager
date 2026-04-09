import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { SeverityBadge } from '../SeverityBadge';
import type { SeverityLevel } from '@/types';

// jsdom converts hex to rgb, so we map expected rgb values
const EXPECTED_RGB: Record<SeverityLevel, string> = {
  'SEV-1': 'rgb(220, 38, 38)',    // #dc2626
  'SEV-2': 'rgb(234, 88, 12)',    // #ea580c
  'SEV-3': 'rgb(217, 119, 6)',    // #d97706
  'SEV-4': 'rgb(37, 99, 235)',    // #2563eb
  'SEV-5': 'rgb(107, 114, 128)',  // #6b7280
};

describe('SeverityBadge', () => {
  const levels: SeverityLevel[] = ['SEV-1', 'SEV-2', 'SEV-3', 'SEV-4', 'SEV-5'];

  levels.forEach((level) => {
    it(`${level} 레벨에 올바른 색상을 렌더링한다`, () => {
      render(<SeverityBadge severity={level} />);
      const badge = screen.getByText(level);
      expect(badge).toBeInTheDocument();
      expect(badge.style.borderColor).toBe(EXPECTED_RGB[level]);
      expect(badge.style.color).toBe(EXPECTED_RGB[level]);
    });
  });
});
