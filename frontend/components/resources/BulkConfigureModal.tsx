"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { fetchResourceThresholds, saveResourceThresholds } from "@/lib/api-functions";
import {
  EVAL_PRESETS,
  bulkUpdate,
  distribution,
  evalMeaning,
  impactFor,
  runPool,
  type BulkChange,
  type ImpactRow,
} from "@/lib/threshold-edit";
import type { ThresholdMetric } from "@/types/api";
import { SourcePill } from "./ThresholdEditModal";

export interface BulkTarget {
  id: string;
  name: string;
}

interface BulkConfigureModalProps {
  resourceType: string;
  targets: BulkTarget[];
  onClose: () => void;
  onApplied: () => void;
}

type Step = 1 | 2 | 3;
type Loaded = Record<string, ThresholdMetric[] | { error: string }>;
interface Draft { on: boolean; action: "set" | "clear" | "keep"; value: string; eval: string }
interface Outcome { id: string; name: string; ok: boolean; message: string }

const STEPS = ["바꿀 값", "영향 보기", "적용"];

/**
 * 같은 타입 리소스 여러 개의 임계치·판단 방식을 한 번에 바꾼다 (docs/specs/bulk-alarm-config).
 * 리소스마다 GET으로 지금 값을 읽어 영향을 보여주고, 적용은 리소스마다 PUT /thresholds를 3개씩 보낸다.
 */
export function BulkConfigureModal({ resourceType, targets, onClose, onApplied }: BulkConfigureModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [loaded, setLoaded] = useState<Loaded>({});
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [running, setRunning] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let alive = true;
    void runPool(targets, async (t) => {
      try {
        const data = await fetchResourceThresholds(t.id);
        if (alive) setLoaded((prev) => ({ ...prev, [t.id]: data.metrics }));
      } catch (e) {
        if (alive) setLoaded((prev) => ({ ...prev, [t.id]: { error: e instanceof Error ? e.message : "불러오지 못함" } }));
      }
    }, 4);
    return () => { alive = false; };
  }, [targets]);

  const loadedCount = Object.keys(loaded).length;
  const metricsOf = (id: string): ThresholdMetric[] | null => {
    const v = loaded[id];
    return Array.isArray(v) ? v : null;
  };

  // 지표 목록: 처음 읽힌 리소스 기준(같은 타입이라 같다)
  const catalog = useMemo(() => {
    const first = targets.map((t) => metricsOf(t.id)).find(Boolean);
    return first ?? [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, targets]);

  const draftOf = (m: ThresholdMetric): Draft => drafts[m.metric] ?? { on: false, action: "set", value: "", eval: "" };
  const patch = (metric: string, p: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [metric]: { ...(prev[metric] ?? { on: false, action: "set", value: "", eval: "" }), ...p } }));

  const changes: BulkChange[] = catalog.flatMap((m) => {
    const d = draftOf(m);
    if (!d.on) return [];
    const value = Number(d.value);
    const action = d.action === "set" && (d.value.trim() === "" || !(value > 0)) ? "keep" : d.action;
    const change: BulkChange = { metric: m.metric, action, eval: d.eval || null };
    if (action === "set") change.value = value;
    return action === "keep" && change.eval === null ? [] : [change];
  });

  const impacts: { change: BulkChange; rows: ImpactRow[] }[] = changes.map((change) => ({
    change,
    rows: targets.map((t) => impactFor(t.id, t.name, metricsOf(t.id)?.find((m) => m.metric === change.metric), change)),
  }));
  // 리소스 단위 적용 대상: 어느 지표든 바뀌는 리소스, 제외 체크 안 한 것
  const applyIds = targets
    .filter((t) => impacts.some(({ rows }) => rows.some((r) => r.id === t.id && (r.kind === "change" || r.kind === "overwrite"))))
    .filter((t) => !excluded.has(t.id))
    .map((t) => t.id);

  const apply = async (ids: string[]) => {
    setRunning(true);
    setStep(3);
    setOutcomes((prev) => prev.filter((o) => !ids.includes(o.id)));
    await runPool(ids, async (id) => {
      const metrics = metricsOf(id) ?? [];
      const body = { set: {}, eval: {}, clear: [] as string[] } as Required<ReturnType<typeof bulkUpdate>>;
      for (const change of changes) {
        const metric = metrics.find((m) => m.metric === change.metric);
        const row = impactFor(id, "", metric, change);
        if (!metric || row.kind === "skip" || row.kind === "same") continue;
        const u = bulkUpdate(change, metric);
        Object.assign(body.set, u.set ?? {});
        Object.assign(body.eval, u.eval ?? {});
        body.clear.push(...(u.clear ?? []));
      }
      await saveResourceThresholds(id, body);
    }, 3, (id, error) => {
      const name = targets.find((t) => t.id === id)?.name ?? id;
      setOutcomes((prev) => [...prev, {
        id, name, ok: !error,
        message: error ? (error instanceof Error ? error.message : String(error)) : "적용됨 · 알람 다시 맞춤",
      }]);
    });
    setRunning(false);
    onApplied();
  };

  const failed = outcomes.filter((o) => !o.ok);
  const succeeded = outcomes.filter((o) => o.ok);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="bulk-config-title"
        className="flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl bg-white shadow-xl">
        <div className="border-b border-slate-100 px-7 pb-4 pt-6">
          <div className="flex items-start justify-between">
            <div>
              <h3 id="bulk-config-title" className="font-headline text-xl font-extrabold">
                알람 설정 — {resourceType} {targets.length}개
              </h3>
              <p className="mt-1 text-sm text-slate-600">
                {step === 1 && "바꿀 지표만 고르세요. 나머지는 그대로 둡니다."}
                {step === 2 && "적용 전에 리소스마다 무엇이 바뀌는지 확인하세요."}
                {step === 3 && (running ? "적용하는 중… 창을 닫아도 이미 보낸 요청은 끝까지 처리됩니다." : "적용을 마쳤습니다.")}
              </p>
            </div>
            <Button variant="ghost" onClick={onClose} icon={<X size={20} />} aria-label="닫기" />
          </div>
          <ol className="mt-4 flex gap-2 text-[13px] font-semibold">
            {STEPS.map((label, i) => (
              <li key={label} className={`rounded-full px-3 py-1.5 ${
                i + 1 === step ? "bg-primary text-white" : i + 1 < step ? "bg-blue-100 text-blue-800" : "bg-slate-100 text-slate-600"}`}>
                {i + 1} {label}{i + 1 < step ? " ✓" : ""}
              </li>
            ))}
          </ol>
        </div>

        <div className="overflow-auto px-7 py-4">
          {loadedCount < targets.length && step !== 3 && (
            <p className="mb-3 text-sm text-slate-500">지금 값을 읽는 중… {loadedCount}/{targets.length}</p>
          )}

          {step === 1 && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-xs font-semibold text-slate-600">
                  <th className="py-3 pr-3">지표</th>
                  <th className="py-3 pr-3">지금 값 분포 ({targets.length}개)</th>
                  <th className="py-3">동작</th>
                </tr>
              </thead>
              <tbody>
                {catalog.map((m) => {
                  const d = draftOf(m);
                  const values = targets.map((t) => {
                    const row = metricsOf(t.id)?.find((x) => x.metric === m.metric);
                    return row ? (row.off ? "off" : String(row.value)) : "—";
                  });
                  const evals = targets.map((t) => metricsOf(t.id)?.find((x) => x.metric === m.metric)?.eval ?? "—");
                  const id = `bulk-${m.metric}`;
                  return (
                    <FragmentRows key={m.metric}>
                      <tr className={`border-b border-slate-50 ${d.on ? "bg-blue-50/50" : ""}`}>
                        <td className="py-3 pr-3 font-semibold">
                          <label className="flex items-center gap-2.5">
                            <input type="checkbox" checked={d.on} onChange={(e) => patch(m.metric, { on: e.target.checked })} className="h-4 w-4" />
                            {m.label}
                          </label>
                        </td>
                        <td className="py-3 pr-3 text-[13px] text-slate-600">{distribution(values)}</td>
                        <td className="py-3 text-[13px]">
                          {!d.on ? <span className="text-slate-500">손대지 않음</span> : (
                            <div className="flex flex-wrap items-center gap-3">
                              <label className="flex items-center gap-1.5">
                                <input type="radio" name={`${id}-a`} checked={d.action === "set"} onChange={() => patch(m.metric, { action: "set" })} />
                                값 지정
                              </label>
                              <input aria-label={`${m.label} 새 값`} inputMode="decimal" value={d.value} disabled={d.action !== "set"}
                                onChange={(e) => patch(m.metric, { value: e.target.value })}
                                className="h-10 w-20 rounded-lg border border-slate-300 px-2.5 disabled:bg-slate-50" />
                              <span className="text-slate-600">{m.unit}</span>
                              <label className="flex items-center gap-1.5">
                                <input type="radio" name={`${id}-a`} checked={d.action === "clear"} onChange={() => patch(m.metric, { action: "clear" })} />
                                개별값 해제
                              </label>
                              <label className="flex items-center gap-1.5">
                                <input type="radio" name={`${id}-a`} checked={d.action === "keep"} onChange={() => patch(m.metric, { action: "keep" })} />
                                임계치 그대로
                              </label>
                            </div>
                          )}
                        </td>
                      </tr>
                      {d.on && !m.eval_locked && (
                        <tr className="border-b border-slate-50 bg-blue-50/50">
                          <td className="py-2.5 pl-7 pr-3 text-[13px] text-slate-600">└ 판단 방식</td>
                          <td className="py-2.5 pr-3 text-[13px] text-slate-600">{distribution(evals)}</td>
                          <td className="py-2.5 text-[13px]">
                            <div className="flex items-center gap-2.5">
                              <select aria-label={`${m.label} 판단 방식`} value={d.eval} onChange={(e) => patch(m.metric, { eval: e.target.value })}
                                className="h-10 rounded-lg border border-slate-300 bg-white px-2">
                                <option value="">그대로 두기</option>
                                {EVAL_PRESETS.map((p) => <option key={p} value={p}>{p === "1/1" ? "즉시 1/1" : p}</option>)}
                              </select>
                              {d.eval && <span className="text-blue-900">{evalMeaning(d.eval, m.period, null, m.unit, m.direction)}</span>}
                            </div>
                          </td>
                        </tr>
                      )}
                    </FragmentRows>
                  );
                })}
              </tbody>
            </table>
          )}

          {step === 1 && catalog.length > 0 && (
            <p className="mt-3 text-[13px] text-slate-600">
              디스크 경로별 지표(<code className="font-mono">/data</code> 등)는 리소스마다 경로가 달라 리소스 상세의 알람 편집에서 바꿉니다.
            </p>
          )}

          {step === 2 && impacts.map(({ change, rows }) => {
            const metric = catalog.find((m) => m.metric === change.metric);
            const count = (k: ImpactRow["kind"]) => rows.filter((r) => r.kind === k).length;
            const shown = showAll ? rows : rows.slice(0, 8);
            return (
              <section key={change.metric} className="mb-6">
                <h4 className="mb-2 text-sm font-bold">
                  {metric?.label}
                  {change.action === "set" ? ` → ${change.value} ${metric?.unit ?? ""}` : change.action === "clear" ? " → 개별값 해제" : ""}
                  {change.eval ? ` · ${change.eval}` : ""}
                </h4>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  <Stat label="바뀜" value={count("change") + count("overwrite")} tone="primary" />
                  <Stat label="기존 개별값 덮어씀" value={count("overwrite")} tone="warn" />
                  <Stat label="이미 같음" value={count("same")} />
                  <Stat label="건너뜀" value={count("skip")} />
                </div>
                <div className="mt-3 overflow-hidden rounded-lg border border-slate-100">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs font-semibold text-slate-600">
                      <tr><th className="w-10 px-3 py-2.5"></th><th className="py-2.5 pr-3">리소스</th><th className="py-2.5 pr-3">지금</th><th className="py-2.5">적용 후</th></tr>
                    </thead>
                    <tbody>
                      {shown.map((r) => {
                        const active = r.kind === "change" || r.kind === "overwrite";
                        return (
                          <tr key={r.id} className={`border-t border-slate-50 ${r.kind === "overwrite" ? "bg-amber-50" : ""} ${active ? "" : "text-slate-500"}`}>
                            <td className="px-3 py-2.5">
                              {active && (
                                <input type="checkbox" aria-label={`${r.name} 포함`} checked={!excluded.has(r.id)}
                                  onChange={(e) => setExcluded((prev) => {
                                    const next = new Set(prev);
                                    if (e.target.checked) next.delete(r.id); else next.add(r.id);
                                    return next;
                                  })} className="h-4 w-4" />
                              )}
                            </td>
                            <td className="py-2.5 pr-3 font-semibold">{r.name}</td>
                            <td className="py-2.5 pr-3">{r.before} <SourcePill source={r.beforeSource} /></td>
                            <td className={`py-2.5 ${r.kind === "overwrite" ? "font-semibold text-amber-800" : active ? "font-semibold text-primary" : ""}`}>
                              {r.after}{r.kind === "overwrite" ? " · 기존 개별값 덮어씀" : ""}{r.reason ? ` · ${r.reason}` : ""}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {rows.length > shown.length && (
                    <button type="button" onClick={() => setShowAll(true)} className="w-full border-t border-slate-50 px-3 py-2.5 text-left text-[13px] text-primary">
                      나머지 {rows.length - shown.length}개 더 보기
                    </button>
                  )}
                </div>
              </section>
            );
          })}
          {step === 2 && (
            <div className="rounded-lg bg-indigo-50 px-4 py-3 text-[13px] text-blue-900">
              적용하면 {applyIds.length}개 리소스에 값이 <b>고정</b>됩니다. 이후 고객사 기본값을 바꿔도 이 리소스들은 따라가지 않습니다.
              M/N을 키우면 순간 튐에는 덜 울리는 대신 알람이 그만큼 늦게 울립니다.
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div>
                <div className="mb-2 flex justify-between text-sm">
                  <span><b>{applyTotal(outcomes, applyIds)}개 중 {succeeded.length} 성공</b>{failed.length > 0 && <> · <span className="font-semibold text-red-700">{failed.length} 실패</span></>}</span>
                  <span className="text-slate-600">{running ? "진행 중" : "완료"}</span>
                </div>
                <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100" role="progressbar"
                  aria-valuenow={outcomes.length} aria-valuemax={applyTotal(outcomes, applyIds)}>
                  <div className="bg-primary" style={{ width: `${pct(succeeded.length, applyTotal(outcomes, applyIds))}%` }} />
                  <div className="bg-red-600" style={{ width: `${pct(failed.length, applyTotal(outcomes, applyIds))}%` }} />
                </div>
              </div>
              <ul className="overflow-hidden rounded-lg border border-slate-100 text-sm">
                {[...failed, ...succeeded].map((o) => (
                  <li key={o.id} className={`flex gap-3 border-t border-slate-50 px-3.5 py-2.5 first:border-t-0 ${o.ok ? "" : "bg-red-50"}`}>
                    <span className={o.ok ? "font-bold text-green-700" : "font-bold text-red-700"}>{o.ok ? "✓" : "✕"}</span>
                    <span className="w-40 shrink-0 font-semibold">{o.name}</span>
                    <span className={o.ok ? "text-slate-600" : "text-red-900"}>{o.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="flex justify-between gap-2 border-t border-slate-100 px-7 pb-6 pt-4">
          <div>{step === 2 && <Button variant="secondary" onClick={() => setStep(1)}>← 뒤로</Button>}</div>
          <div className="flex gap-2">
            {step === 1 && <>
              <Button variant="secondary" onClick={onClose}>취소</Button>
              <Button variant="primary" disabled={changes.length === 0 || loadedCount < targets.length} onClick={() => { setShowAll(false); setStep(2); }}>
                영향 보기 →
              </Button>
            </>}
            {step === 2 && (
              <Button variant="primary" disabled={applyIds.length === 0} onClick={() => apply(applyIds)}>
                {applyIds.length}개 적용
              </Button>
            )}
            {step === 3 && <>
              {failed.length > 0 && !running && (
                <Button variant="secondary" onClick={() => apply(failed.map((f) => f.id))}>실패만 재시도 ({failed.length})</Button>
              )}
              <Button variant="primary" onClick={onClose}>닫기</Button>
            </>}
          </div>
        </div>
      </div>
    </div>
  );
}

function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "primary" | "warn" }) {
  const box = tone === "warn" ? "border-amber-200 bg-amber-50" : "border-slate-200";
  const text = tone === "warn" ? "text-amber-800" : tone === "primary" ? "text-primary" : "";
  return (
    <div className={`rounded-lg border px-3.5 py-3 ${box}`}>
      <div className={`text-xs ${tone === "warn" ? "text-amber-800" : "text-slate-600"}`}>{label}</div>
      <div className={`font-headline text-2xl font-extrabold ${text}`}>{value}</div>
    </div>
  );
}

function applyTotal(outcomes: Outcome[], applyIds: string[]): number {
  return Math.max(applyIds.length, outcomes.length);
}

function pct(n: number, total: number): number {
  return total === 0 ? 0 : (n / total) * 100;
}
