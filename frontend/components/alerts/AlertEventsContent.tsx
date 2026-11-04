"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BellOff, BellRing, Clock, RefreshCw, ShieldOff } from "lucide-react";

import { fetchAlertEvents, fetchAlertSilences } from "@/lib/api-functions";
import type {
  AlertEventRow,
  AlertEventSummary,
  AlertSilence,
} from "@/types/api";

const DAY_OPTIONS = [1, 3, 7, 14];

const ACTION_FILTERS = [
  { value: "", label: "All" },
  { value: "notify", label: "Sent" },
  { value: "suppress", label: "Suppressed" },
  { value: "pending", label: "Pending" },
] as const;

const ACTION_STYLES: Record<string, string> = {
  notify: "bg-red-50 text-red-700 border-red-200",
  suppress: "bg-slate-100 text-slate-600 border-slate-200",
  pending: "bg-amber-50 text-amber-700 border-amber-200",
};

const SEVERITY_STYLES: Record<string, string> = {
  "SEV-1": "bg-red-100 text-red-700",
  "SEV-2": "bg-orange-100 text-orange-700",
  "SEV-3": "bg-amber-100 text-amber-700",
  "SEV-4": "bg-sky-100 text-sky-700",
  "SEV-5": "bg-slate-100 text-slate-600",
};

function formatTime(iso: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", { hour12: false });
}

function SummaryCards({ summary, days }: { summary: AlertEventSummary; days: number }) {
  const cards = [
    { label: "Sent", value: summary.notify, icon: BellRing, tone: "text-red-600" },
    { label: "Suppressed", value: summary.suppress, icon: BellOff, tone: "text-slate-600" },
    { label: "Pending", value: summary.pending, icon: Clock, tone: "text-amber-600" },
  ];
  const rate = Math.round((summary.suppression_rate ?? 0) * 1000) / 10;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(({ label, value, icon: Icon, tone }) => (
        <div key={label} className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500">
            <Icon size={14} className={tone} />
            {label}
          </div>
          <div className={`mt-2 text-2xl font-extrabold ${tone}`}>{value ?? 0}</div>
        </div>
      ))}
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-500">Suppression Rate</div>
        <div className="mt-2 text-2xl font-extrabold text-slate-800">{rate}%</div>
        <p className="mt-1 text-xs text-slate-500">
          Last {days} days · based on {summary.notify + summary.suppress} finalized
        </p>
      </div>
    </div>
  );
}

function SilenceBanner({ silences }: { silences: AlertSilence[] }) {
  const active = silences.filter((s) => s.active);
  if (active.length === 0) return null;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
      <div className="flex items-center gap-2 text-sm font-bold text-amber-800">
        <ShieldOff size={15} />
        {active.length} active maintenance window(s)
      </div>
      <ul className="mt-2 space-y-1 text-xs text-amber-900">
        {active.map((s) => (
          <li key={s.id}>
            <span className="font-semibold">
              {s.customer_id || "All Customers"}
              {s.resource_id ? ` · ${s.resource_id}` : ""}
              {s.severity ? ` · ${s.severity}` : ""}
            </span>
            {" — "}
            {s.reason || "No reason given"} (until {formatTime(s.ends_at)})
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-amber-700">
        Alarms matching these conditions will not alert until the window ends.
      </p>
    </div>
  );
}

function EventRow({ row }: { row: AlertEventRow }) {
  const [open, setOpen] = useState(false);
  const style = ACTION_STYLES[row.action] ?? ACTION_STYLES.suppress;

  return (
    <>
      <tr
        className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
        onClick={() => setOpen((v) => !v)}
      >
        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">
          {formatTime(row.occurred_at)}
        </td>
        <td className="px-3 py-2">
          {/* 고객이 직접 만든 알람은 우리 리소스 식별이 없다 — 알람 이름으로 보여준다 */}
          <div className="text-sm font-medium text-slate-800">
            {row.resource_id || row.alarm_name || "-"}
            {!row.resource_id && row.alarm_name && (
              <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">Customer alarm</span>
            )}
          </div>
          <div className="text-xs text-slate-500">
            {[row.resource_type, row.metric_key].filter(Boolean).join(" · ")}
          </div>
        </td>
        <td className="whitespace-nowrap px-3 py-2">
          <span
            className={`rounded px-1.5 py-0.5 text-xs font-bold ${
              SEVERITY_STYLES[row.severity] ?? SEVERITY_STYLES["SEV-5"]
            }`}
          >
            {row.severity || "-"}
          </span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">
          {row.previous_state} → {row.state}
        </td>
        <td className="whitespace-nowrap px-3 py-2">
          <span className={`rounded border px-2 py-0.5 text-xs font-bold ${style}`}>
            {row.action_label}
          </span>
        </td>
        <td className="px-3 py-2 text-xs text-slate-600">{row.reason_label}</td>
      </tr>
      {open && (
        <tr className="border-t border-slate-100 bg-slate-50/70">
          <td colSpan={6} className="px-4 py-3">
            <p className="text-sm text-slate-700">{row.explanation}</p>
            {row.quarantined_until && (
              <p className="mt-1 text-xs text-amber-700">
                Quarantined until: {formatTime(row.quarantined_until)}
              </p>
            )}
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-slate-500 sm:grid-cols-2">
              <div>
                <dt className="inline font-semibold">Alarm </dt>
                <dd className="inline">{row.alarm_name || "-"}</dd>
              </div>
              <div>
                <dt className="inline font-semibold">Account/Region </dt>
                <dd className="inline">
                  {row.account_id || "-"} / {row.region || "-"}
                </dd>
              </div>
              {row.state_reason && (
                <div className="sm:col-span-2">
                  <dt className="inline font-semibold">CloudWatch reason </dt>
                  <dd className="inline">{row.state_reason}</dd>
                </div>
              )}
              {row.group_id && (
                <div className="sm:col-span-2">
                  <dt className="inline font-semibold">Group </dt>
                  <dd className="inline">
                    {row.group_id}
                    {row.finalized ? " (finalized)" : " (awaiting finalization)"}
                  </dd>
                </div>
              )}
            </dl>
          </td>
        </tr>
      )}
    </>
  );
}

export function AlertEventsContent() {
  const [days, setDays] = useState(1);
  const [action, setAction] = useState("");
  const [rows, setRows] = useState<AlertEventRow[]>([]);
  const [summary, setSummary] = useState<AlertEventSummary | null>(null);
  const [silences, setSilences] = useState<AlertSilence[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchAlertEvents({ days, action: action || undefined });
      setRows(data.events);
      setSummary(data.summary);
      setTruncated(data.truncated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load alert history");
    } finally {
      setLoading(false);
    }
  }, [days, action]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    fetchAlertSilences()
      .then((d) => setSilences(d.silences))
      .catch(() => setSilences([]));
  }, []);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-headline text-2xl font-bold text-slate-800">Alert History</h1>
          <p className="mt-1 text-sm text-slate-500">
            Shows whether an alert was sent when an alarm fired, and if not, why.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
        >
          <RefreshCw size={13} /> Refresh
        </button>
      </header>

      <SilenceBanner silences={silences} />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                days === d
                  ? "bg-slate-800 text-white"
                  : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              Last {d} days
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-1">
          {ACTION_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setAction(f.value)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                action === f.value
                  ? "bg-slate-800 text-white"
                  : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {summary && <SummaryCards summary={summary} days={days} />}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px]">
            <thead className="bg-slate-50 text-left text-xs font-bold uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Resource</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                    Loading…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                    No alarm events were processed in this period.
                  </td>
                </tr>
              ) : (
                rows.map((r) => <EventRow key={`${r.series_id}#${r.event_key}`} row={r} />)
              )}
            </tbody>
          </table>
        </div>
        {truncated && (
          <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
            Too many events to show them all. Summary numbers cover everything.
          </p>
        )}
      </div>

      <p className="text-xs text-slate-400">
        &lsquo;Sent&rsquo; means the event passed suppression rules and was handed to notification channels. Where it actually goes depends on
        the conditions (severity, type) in Settings &gt; Notification Channels. No suppression rule ever applies to SEV-1.
      </p>
    </div>
  );
}
