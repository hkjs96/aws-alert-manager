import { ArrowUp, ArrowDown } from "lucide-react";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { SourceBadge } from "@/components/shared/SourceBadge";
import type { AlarmConfig } from "@/types";

export interface EditableConfig extends AlarmConfig {
  dirty: boolean;
}

const STATE_COLORS: Record<string, string> = {
  OK: "text-green-700 bg-green-100",
  ALARM: "text-error bg-error/10",
  INSUFFICIENT: "text-amber-700 bg-amber-100",
  OFF: "text-slate-500 bg-slate-100",
  MUTED: "text-purple-700 bg-purple-100",
};

interface AlarmRowProps {
  row: EditableConfig;
  index: number;
  onUpdate: (idx: number, patch: Partial<EditableConfig>) => void;
}

export function AlarmRow({ row, index, onUpdate }: AlarmRowProps) {
  const stateColor = STATE_COLORS[row.state] ?? "text-slate-500 bg-slate-100";
  const DirIcon = row.direction === ">" ? ArrowUp : ArrowDown;

  return (
    <tr className="bg-white/30 hover:bg-white transition-colors">
      <td className="pl-8 py-5">
        <input
          type="checkbox"
          checked={row.monitoring}
          onChange={(e) => onUpdate(index, { monitoring: e.target.checked })}
          className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
        />
      </td>
      <td className="px-4 py-5 font-semibold text-sm">{row.metric_name}</td>
      <td className="px-4 py-5">
        <input
          type="number"
          value={row.threshold}
          onChange={(e) => onUpdate(index, { threshold: Number(e.target.value) })}
          className="w-20 bg-white border border-slate-200 rounded px-2 py-1 font-mono text-sm focus:ring-1 focus:ring-primary outline-none"
        />
      </td>
      <td className="px-4 py-5 text-sm text-slate-500">{row.unit}</td>
      <td className="px-4 py-5 text-center">
        <DirIcon size={16} className="text-error mx-auto" />
      </td>
      <td className="px-4 py-5">
        <SeverityBadge severity={row.severity} />
      </td>
      <td className="px-4 py-5">
        <SourceBadge source={row.source} />
      </td>
      <td className="px-4 py-5">
        <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-tight ${stateColor}`}>
          {row.state}
        </span>
      </td>
      <td className="pr-8 py-5 text-right font-mono text-sm font-medium">
        {row.current_value !== null ? row.current_value : "—"}
      </td>
    </tr>
  );
}
