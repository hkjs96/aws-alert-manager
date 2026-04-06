import type { SeverityLevel } from "@/types";
import { SEVERITY_COLORS, SEVERITY_LABELS } from "@/lib/constants";

interface SeverityBadgeProps {
  severity: SeverityLevel;
  showLabel?: boolean;
}

export function SeverityBadge({ severity, showLabel = false }: SeverityBadgeProps) {
  const color = SEVERITY_COLORS[severity];
  const label = SEVERITY_LABELS[severity];

  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{ borderColor: color, color }}
      title={`${severity} ${label}`}
    >
      {severity}
      {showLabel && <span className="ml-1">{label}</span>}
    </span>
  );
}
