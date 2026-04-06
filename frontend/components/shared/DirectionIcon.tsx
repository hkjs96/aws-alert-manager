import type { DirectionSimple } from "@/types";
import { DIRECTION_STYLES } from "@/lib/constants";

interface DirectionIconProps {
  direction: DirectionSimple;
}

export function DirectionIcon({ direction }: DirectionIconProps) {
  const style = DIRECTION_STYLES[direction];

  return (
    <span
      className="inline-flex items-center text-sm font-bold"
      style={{ color: style.color }}
      title={style.label}
    >
      {style.icon}
    </span>
  );
}
