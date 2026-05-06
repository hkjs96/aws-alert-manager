import type { SeverityLevel } from '@/types';

const SEVERITY_CLASSES: Record<SeverityLevel, string> = {
  'SEV-1': 'bg-red-100 text-red-700 border-red-300',
  'SEV-2': 'bg-orange-100 text-orange-700 border-orange-300',
  'SEV-3': 'bg-amber-100 text-amber-700 border-amber-300',
  'SEV-4': 'bg-blue-100 text-blue-700 border-blue-300',
  'SEV-5': 'bg-slate-100 text-slate-600 border-slate-300',
};

interface SeverityBadgeProps {
  severity: SeverityLevel;
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_CLASSES[severity]}`}>
      {severity}
    </span>
  );
}
