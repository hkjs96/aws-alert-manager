"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { useToast } from "@/components/shared/Toast";
import { fetchResourceThresholds, saveResourceThresholds } from "@/lib/api-functions";
import {
  EVAL_PRESETS,
  SOURCE_LABEL,
  buildUpdate,
  countChanges,
  evalMeaning,
  initialDraft,
  type MetricDraft,
} from "@/lib/threshold-edit";
import type { ThresholdMetric, ThresholdSource } from "@/types/api";

const SOURCE_STYLE: Record<ThresholdSource, string> = {
  resource: "bg-blue-100 text-blue-800",
  customer: "bg-slate-200 text-slate-700",
  system: "bg-slate-100 text-slate-600",
};

export function SourcePill({ source }: { source: ThresholdSource }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${SOURCE_STYLE[source]}`}>
      {SOURCE_LABEL[source]}
    </span>
  );
}

interface ThresholdEditModalProps {
  resourceId: string;
  resourceName: string;
  resourceType: string;
  onClose: () => void;
  onSaved: () => void;
}

/** 리소스 하나의 임계치·판단 방식 편집. 값은 리소스의 Threshold_* 태그로 저장된다. */
export function ThresholdEditModal({ resourceId, resourceName, resourceType, onClose, onSaved }: ThresholdEditModalProps) {
  const { showToast } = useToast();
  const [metrics, setMetrics] = useState<ThresholdMetric[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, MetricDraft>>({});
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchResourceThresholds(resourceId)
      .then((data) => {
        setMetrics(data.metrics);
        setDrafts(Object.fromEntries(data.metrics.map((m) => [m.metric, initialDraft(m)])));
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : "Failed to load"));
  }, [resourceId]);

  const update = useMemo(() => {
    if (!metrics) return null;
    try {
      return buildUpdate(metrics, drafts);
    } catch {
      return null;
    }
  }, [metrics, drafts]);
  const changes = update ? countChanges(update) : 0;

  const patch = (metric: string, p: Partial<MetricDraft>) =>
    setDrafts((prev) => ({ ...prev, [metric]: { ...prev[metric], ...p } as MetricDraft }));

  const handleSave = async () => {
    if (!metrics) return;
    setError("");
    let body;
    try {
      body = buildUpdate(metrics, drafts);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setSaving(true);
    try {
      await saveResourceThresholds(resourceId, body);
      showToast("success", "Alarm settings saved.");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="threshold-edit-title"
        className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-2xl bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-slate-100 px-7 pb-4 pt-6">
          <div>
            <h3 id="threshold-edit-title" className="font-headline text-xl font-extrabold">Edit Alarms</h3>
            <p className="mt-1 text-sm text-slate-600">{resourceName} · {resourceType} · Leave blank to keep the current value</p>
          </div>
          <Button variant="ghost" onClick={onClose} icon={<X size={20} />} aria-label="Close" />
        </div>

        <div className="overflow-auto px-7 py-2">
          {loadError && <p className="py-6 text-sm text-red-700">{loadError}</p>}
          {!metrics && !loadError && <p className="py-6 text-sm text-slate-500">Loading…</p>}
          {metrics && (
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-xs font-semibold text-slate-600">
                  <th className="py-3 pr-3">Metric</th>
                  <th className="py-3 pr-3">Threshold</th>
                  <th className="py-3 pr-3">Evaluation</th>
                  <th className="py-3 pr-3">Meaning</th>
                  <th className="py-3">Source</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((m) => (
                  <MetricRow key={m.metric} metric={m} draft={drafts[m.metric]} onChange={(p) => patch(m.metric, p)} />
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="mx-7 mt-2 rounded-lg bg-indigo-50 px-4 py-3 text-sm leading-relaxed text-blue-900">
          Changed values are <b>pinned</b> to this resource and saved as its <code className="font-mono">Threshold_*</code> tags, so they also
          show in the AWS console. To follow the customer default again, click <b>Clear Resource Value</b>. Period and statistic are fixed per metric.
        </div>
        {error && <p className="mx-7 mt-3 text-sm text-red-700" role="alert">{error}</p>}

        <div className="flex justify-end gap-2 px-7 pb-6 pt-5">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <LoadingButton isLoading={saving} disabled={changes === 0} onClick={handleSave}
            className="rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50">
            {changes > 0 ? `Save (${changes} ${changes === 1 ? "change" : "changes"})` : "Save"}
          </LoadingButton>
        </div>
      </div>
    </div>
  );
}

function MetricRow({ metric, draft, onChange }: {
  metric: ThresholdMetric;
  draft: MetricDraft | undefined;
  onChange: (p: Partial<MetricDraft>) => void;
}) {
  if (!draft) return null;
  const inputId = `thr-${metric.metric}`;
  const shownValue = draft.value.trim() !== "" ? Number(draft.value) : draft.clear
    ? (metric.customer_default ?? metric.system_default) : metric.value;
  const custom = !EVAL_PRESETS.includes(draft.eval as (typeof EVAL_PRESETS)[number]);
  const changed = draft.value.trim() !== "" || draft.clear || draft.eval !== metric.eval || draft.off !== metric.off;

  return (
    <tr className={`border-b border-slate-50 align-middle ${changed ? "bg-blue-50/50" : ""}`}>
      <td className="py-3 pr-3">
        <label htmlFor={inputId} className="font-semibold">{metric.label}</label>
        <div className="text-xs text-slate-600">
          {metric.statistic ?? ""}{metric.period ? ` · ${metric.period >= 60 ? `${metric.period / 60} min` : `${metric.period} s`} period` : ""}
        </div>
      </td>
      <td className="py-3 pr-3">
        {draft.off ? (
          <span className="text-slate-500">Off</span>
        ) : (
          <div className="flex items-center gap-1.5">
            <input id={inputId} inputMode="decimal" value={draft.value}
              placeholder={metric.value === null ? "" : String(draft.clear ? (metric.customer_default ?? metric.system_default) : metric.value)}
              onChange={(e) => onChange({ value: e.target.value, clear: false })}
              className="h-10 w-20 rounded-lg border border-slate-300 px-2.5 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15" />
            <span className="text-slate-600">{metric.unit}</span>
          </div>
        )}
      </td>
      <td className="py-3 pr-3">
        {metric.eval_locked ? (
          <span className="text-slate-600">Immediate {metric.eval} <span className="text-xs">(fixed)</span></span>
        ) : (
          <div className="flex items-center gap-1.5">
            <select aria-label={`${metric.label} evaluation`} value={custom ? "custom" : draft.eval}
              onChange={(e) => onChange({ eval: e.target.value === "custom" ? "4/6" : e.target.value })}
              className="h-10 rounded-lg border border-slate-300 bg-white px-2">
              {EVAL_PRESETS.map((p) => <option key={p} value={p}>{p === "1/1" ? "Immediate 1/1" : p}</option>)}
              <option value="custom">Custom…</option>
            </select>
            {custom && (
              <input aria-label={`${metric.label} custom evaluation`} value={draft.eval}
                onChange={(e) => onChange({ eval: e.target.value })}
                className="h-10 w-16 rounded-lg border border-slate-300 px-2 font-mono" />
            )}
          </div>
        )}
      </td>
      <td className="py-3 pr-3 text-[13px] text-slate-700">
        {draft.off ? "No alarm will be created"
          : metric.eval_locked ? "Availability metric — alarms immediately on a single breach"
            : evalMeaning(draft.eval, metric.period, shownValue, metric.unit, metric.direction)}
      </td>
      <td className="py-3">
        <div className="flex flex-col items-start gap-1.5">
          <SourcePill source={draft.clear ? (metric.customer_default !== null ? "customer" : "system") : metric.source} />
          {metric.source === "resource" && !draft.clear && !draft.off && (
            <button type="button" onClick={() => onChange({ clear: true, value: "" })}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">Clear Resource Value</button>
          )}
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            <input type="checkbox" checked={draft.off} onChange={(e) => onChange({ off: e.target.checked })} />
            Turn Off
          </label>
        </div>
      </td>
    </tr>
  );
}
