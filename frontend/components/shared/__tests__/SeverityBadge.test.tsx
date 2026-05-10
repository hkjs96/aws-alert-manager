import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { SeverityBadge } from '../SeverityBadge';
import type { SeverityLevel } from '@/types';

const EXPECTED_CLASSES: Record<SeverityLevel, string[]> = {
  'SEV-1': ['bg-red-100', 'text-red-700', 'border-red-300'],
  'SEV-2': ['bg-orange-100', 'text-orange-700', 'border-orange-300'],
  'SEV-3': ['bg-amber-100', 'text-amber-700', 'border-amber-300'],
  'SEV-4': ['bg-blue-100', 'text-blue-700', 'border-blue-300'],
  'SEV-5': ['bg-slate-100', 'text-slate-600', 'border-slate-300'],
};

describe('SeverityBadge', () => {
  const levels: SeverityLevel[] = ['SEV-1', 'SEV-2', 'SEV-3', 'SEV-4', 'SEV-5'];

  levels.forEach((level) => {
    it(`${level} 레벨에 올바른 Tailwind 클래스를 렌더링한다`, () => {
      render(<SeverityBadge severity={level} />);
      const badge = screen.getByText(level);
      expect(badge).toBeInTheDocument();
      for (const cls of EXPECTED_CLASSES[level]) {
        expect(badge).toHaveClass(cls);
      }
    });
  });
});
