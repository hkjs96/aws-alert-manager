import type { SourceType } from '@/types';

const SOURCE_STYLES: Record<SourceType, string> = {
  System:   'bg-gray-100 text-gray-700',
  Customer: 'bg-blue-100 text-blue-700',
  Custom:   'bg-purple-100 text-purple-700',
};

interface SourceBadgeProps {
  source: SourceType;
}

export function SourceBadge({ source }: SourceBadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${SOURCE_STYLES[source]}`}
    >
      {source}
    </span>
  );
}
