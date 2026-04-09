import { SourceBadge } from "@/components/shared/SourceBadge";
import type { AlarmConfig, DirectionSimple, SeverityLevel } from "@/types";

const UNIT_OPTIONS = [
  "Percent", "Bytes", "Kilobytes", "Megabytes", "Gigabytes", "Terabytes",
  "Count", "Count/Second",
  "Seconds", "Milliseconds", "Microseconds",
  "Bits", "Bits/Second", "Bytes/Second",
  "None",
] as const;

const DIRECTION_OPTIONS = [
  { value: ">", label: ">" },
  { value: ">=", label: ">=" },
  { value: "<", label: "<" },
  { value: "<=", label: "<=" },
] as const;

const SEVERITY_OPTIONS: SeverityLevel[] = ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"];

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
      <td className="px-4 py-5">
        <select
          value={row.unit}
          onChange={(e) => onUpdate(index, { unit: e.target.value })}
          className="bg-white border border-slate-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-primary outline-none min-w-[100px]"
        >
          {UNIT_OPTIONS.map((u) => (
            <option key={u} value={u}>{u}</option>
          ))}
        </select>
      </td>
      <td className="px-4 py-5 text-center">
        <select
          value={row.direction}
          onChange={(e) => onUpdate(index, { direction: e.target.value as DirectionSimple })}
          className="bg-white border border-slate-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-primary outline-none"
        >
          {DIRECTION_OPTIONS.map((d) => (
            <option key={d.value} value={d.value}>{d.label}</option>
          ))}
        </select>
      </td>
      <td className="px-4 py-5">
        <select
          value={row.severity}
          onChange={(e) => onUpdate(index, { severity: e.target.value as SeverityLevel })}
          className="bg-white border border-slate-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-primary outline-none"
        >
          {SEVERITY_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
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
