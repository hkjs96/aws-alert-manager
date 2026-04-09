import type { SeverityLevel } from '@/types';

const SEVERITY_COLORS: Record<SeverityLevel, string> = {
  'SEV-1': '#dc2626',
  'SEV-2': '#ea580c',
  'SEV-3': '#d97706',
  'SEV-4': '#2563eb',
  'SEV-5': '#6b7280',
};

interface SeverityBadgeProps {
  severity: SeverityLevel;
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const color = SEVERITY_COLORS[severity];

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-white border"
      style={{ borderColor: color, color }}
    >
      {severity}
    </span>
  );
}
