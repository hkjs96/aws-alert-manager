import type { SourceType } from "@/types";
import { SOURCE_BADGE_STYLES } from "@/lib/constants";

interface SourceBadgeProps {
  source: SourceType;
}

export function SourceBadge({ source }: SourceBadgeProps) {
  const style = SOURCE_BADGE_STYLES[source];

  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: style.bg, color: style.text }}
    >
      {source}
    </span>
  );
}
