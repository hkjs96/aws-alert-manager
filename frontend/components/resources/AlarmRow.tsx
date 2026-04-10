import { useState } from "react";
import { SlidersHorizontal, ChevronDown, ChevronUp } from "lucide-react";
import { SourceBadge } from "@/components/shared/SourceBadge";
import type { AlarmConfig, DirectionSimple, SeverityLevel, TreatMissingData, AlarmStatistic } from "@/types";

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
const STATISTIC_OPTIONS: AlarmStatistic[] = ["Average", "Sum", "Maximum", "Minimum", "SampleCount"];
const MISSING_DATA_OPTIONS: { value: TreatMissingData; label: string }[] = [
  { value: "missing", label: "Missing" },
  { value: "breaching", label: "Breaching" },
  { value: "notBreaching", label: "Not Breaching" },
  { value: "ignore", label: "Ignore" },
];
const PERIOD_OPTIONS = [60, 120, 300, 600, 900, 3600];

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

const sel = "bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors";
const inp = "bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 font-mono text-xs focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors";

export function AlarmRow({ row, index, onUpdate }: AlarmRowProps) {
  const stateColor = STATE_COLORS[row.state] ?? "text-slate-500 bg-slate-100";
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronUp : ChevronDown;

  return (
    <>
      <tr className="bg-white/30 hover:bg-white transition-colors">
        <td className="pl-8 py-5">
          <input type="checkbox" checked={row.monitoring}
            onChange={(e) => onUpdate(index, { monitoring: e.target.checked })}
            className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4" />
        </td>
        <td className="px-4 py-5 font-semibold text-sm">{row.metric_name}</td>
        <td className="px-4 py-5">
          <input type="number" value={row.threshold}
            onChange={(e) => onUpdate(index, { threshold: Number(e.target.value) })}
            className={`w-20 ${inp}`} />
        </td>
        <td className="px-4 py-5">
          <select value={row.unit} onChange={(e) => onUpdate(index, { unit: e.target.value })} className={`${sel} min-w-[100px]`}>
            {UNIT_OPTIONS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </td>
        <td className="px-4 py-5 text-center">
          <select value={row.direction} onChange={(e) => onUpdate(index, { direction: e.target.value as DirectionSimple })} className={sel}>
            {DIRECTION_OPTIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </td>
        <td className="px-4 py-5">
          <select value={row.severity} onChange={(e) => onUpdate(index, { severity: e.target.value as SeverityLevel })} className={sel}>
            {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </td>
        <td className="px-4 py-5"><SourceBadge source={row.source} /></td>
        <td className="px-4 py-5">
          <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-tight ${stateColor}`}>{row.state}</span>
        </td>
        <td className="pr-4 py-5 text-right font-mono text-sm font-medium">
          {row.current_value !== null ? row.current_value : "—"}
        </td>
        <td className="pr-4 py-5">
          <button onClick={() => setOpen(!open)}
            className={`group inline-flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-full border transition-all duration-200 ${
              open
                ? "bg-primary text-white border-primary shadow-sm"
                : "bg-white text-slate-500 border-slate-200 hover:border-primary hover:text-primary"
            }`}>
            <SlidersHorizontal size={12} />
            <span className="hidden sm:inline">상세</span>
            <Chevron size={12} />
          </button>
        </td>
      </tr>

      {open && (
        <tr>
          <td />
          <td colSpan={9} className="pb-4 pr-8">
            <div className="mt-1 bg-gradient-to-r from-slate-50 to-white border border-slate-200 rounded-xl p-4 shadow-sm">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">
                Advanced Configuration
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Period</label>
                  <select value={row.period ?? 300} onChange={(e) => onUpdate(index, { period: Number(e.target.value) })} className={`w-full ${sel}`}>
                    {PERIOD_OPTIONS.map((p) => <option key={p} value={p}>{p >= 60 ? `${p / 60}m` : `${p}s`}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Datapoints to Alarm</label>
                  <div className="flex items-center gap-1.5">
                    <input type="number" min={1} max={100} value={row.datapoints_to_alarm ?? 1}
                      onChange={(e) => onUpdate(index, { datapoints_to_alarm: Number(e.target.value) })}
                      className={`w-14 text-center ${inp}`} />
                    <span className="text-slate-400 text-xs font-medium">of</span>
                    <input type="number" min={1} max={100} value={row.evaluation_periods ?? 1}
                      onChange={(e) => onUpdate(index, { evaluation_periods: Number(e.target.value) })}
                      className={`w-14 text-center ${inp}`} />
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Statistic</label>
                  <select value={row.statistic ?? "Average"} onChange={(e) => onUpdate(index, { statistic: e.target.value as AlarmStatistic })} className={`w-full ${sel}`}>
                    {STATISTIC_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Missing Data</label>
                  <select value={row.treat_missing_data ?? "missing"} onChange={(e) => onUpdate(index, { treat_missing_data: e.target.value as TreatMissingData })} className={`w-full ${sel}`}>
                    {MISSING_DATA_OPTIONS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
