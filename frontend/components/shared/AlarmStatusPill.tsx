import type { AlarmState } from "@/types";
import { ALARM_STATE_COLORS } from "@/lib/constants";

interface AlarmStatusPillProps {
  state: AlarmState;
}

const STATE_LABELS: Record<AlarmState, string> = {
  OK: "OK",
  ALARM: "ALARM",
  INSUFFICIENT_DATA: "INSUF",
  OFF: "OFF",
};

export function AlarmStatusPill({ state }: AlarmStatusPillProps) {
  const color = ALARM_STATE_COLORS[state];

  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium text-white"
      style={{ backgroundColor: color }}
    >
      {STATE_LABELS[state]}
    </span>
  );
}
