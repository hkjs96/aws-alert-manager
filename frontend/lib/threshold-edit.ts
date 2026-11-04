import type { ThresholdMetric, ThresholdSource, ThresholdUpdate } from "@/types/api";

/** 판단 방식 선택지 — 그 밖의 값은 "직접 입력" */
export const EVAL_PRESETS = ["1/1", "2/3", "3/5"] as const;

export const SOURCE_LABEL: Record<ThresholdSource, string> = {
  resource: "Resource",
  customer: "Customer default",
  system: "System default",
};

export function parseEval(value: string): { m: number; n: number } | null {
  const match = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(value);
  if (!match) return null;
  const m = Number(match[1]);
  const n = Number(match[2]);
  return m >= 1 && m <= n && n <= 10 ? { m, n } : null;
}

function minutes(seconds: number): string {
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

/** "최근 25분 중 15분 이상 90 %를 넘으면 알람" */
export function evalMeaning(evalValue: string, period: number | null, value: number | null, unit: string, direction: string): string {
  const parsed = parseEval(evalValue);
  const p = period ?? 300;
  const verb = direction.startsWith("<") ? "below" : "above";
  const target = value === null ? "" : ` ${value}${unit ? ` ${unit}` : ""}`;
  if (!parsed || (parsed.m === 1 && parsed.n === 1)) {
    return target ? `Alarm immediately if ${verb}${target} once` : "Alarm immediately on a single breach";
  }
  return `Alarm if ${verb}${target} for ${minutes(parsed.m * p)} of the last ${minutes(parsed.n * p)}`;
}

// ── 단일 편집 ─────────────────────────────────────────

export interface MetricDraft {
  /** 비우면 그대로 둔다 */
  value: string;
  eval: string;
  off: boolean;
  clear: boolean;
}

export function initialDraft(metric: ThresholdMetric): MetricDraft {
  return { value: "", eval: metric.eval, off: metric.off, clear: false };
}

/** 초안 → PUT 본문. 바뀐 게 없으면 빈 객체들. 잘못된 값은 Error. */
export function buildUpdate(metrics: ThresholdMetric[], drafts: Record<string, MetricDraft>): ThresholdUpdate {
  const update: Required<ThresholdUpdate> = { set: {}, eval: {}, clear: [] };
  for (const metric of metrics) {
    const draft = drafts[metric.metric];
    if (!draft) continue;
    if (draft.off !== metric.off) {
      if (draft.off) update.set[metric.metric] = "off";
      else update.clear.push(metric.metric);
    } else if (draft.clear) {
      update.clear.push(metric.metric);
    } else if (draft.value.trim() !== "") {
      const value = Number(draft.value);
      if (!Number.isFinite(value) || value <= 0) throw new Error(`${metric.label}: enter a number greater than 0`);
      if (value !== metric.value || metric.source !== "resource") update.set[metric.metric] = value;
    }
    if (!metric.eval_locked && draft.eval !== metric.eval) {
      if (!parseEval(draft.eval)) throw new Error(`${metric.label}: evaluation must be M/N (1 ≤ M ≤ N ≤ 10)`);
      update.eval[metric.metric] = draft.eval === metric.eval_default ? null : draft.eval;
    }
  }
  return update;
}

export function countChanges(update: ThresholdUpdate): number {
  return Object.keys(update.set ?? {}).length + Object.keys(update.eval ?? {}).length + (update.clear ?? []).length;
}

// ── 벌크 ──────────────────────────────────────────────

export interface BulkChange {
  metric: string;
  /** "set": 값 지정 / "clear": 개별값 해제 / "keep": 임계치는 그대로 */
  action: "set" | "clear" | "keep";
  value?: number;
  /** null = 그대로 두기 */
  eval: string | null;
}

export type ImpactKind = "change" | "overwrite" | "same" | "skip";

export interface ImpactRow {
  id: string;
  name: string;
  kind: ImpactKind;
  before: string;
  beforeSource: ThresholdSource;
  after: string;
  reason?: string;
}

function fmt(value: number | null, evalValue: string, withEval: boolean): string {
  const v = value === null ? "—" : String(value);
  return withEval ? `${v} · ${evalValue}` : v;
}

/** 리소스 하나에 이 변경을 적용하면 어떻게 되나. 끈 알람은 다시 켜지 않는다(단일 편집에서만). */
export function impactFor(id: string, name: string, metric: ThresholdMetric | undefined, change: BulkChange): ImpactRow {
  const withEval = change.eval !== null;
  if (!metric) {
    return { id, name, kind: "skip", before: "—", beforeSource: "system", after: "Skipped", reason: "No alarm for this metric" };
  }
  const before = fmt(metric.value, metric.eval, withEval);
  if (metric.off) {
    return { id, name, kind: "skip", before: "off", beforeSource: metric.source, after: "Skipped", reason: "Alarm is off; left as is" };
  }
  if (withEval && metric.eval_locked) {
    return { id, name, kind: "skip", before, beforeSource: metric.source, after: "Skipped", reason: "Evaluation is fixed for this metric" };
  }
  let afterValue = metric.value;
  let afterSource: ThresholdSource = metric.source;
  if (change.action === "set" && change.value !== undefined) {
    afterValue = change.value;
    afterSource = "resource";
  } else if (change.action === "clear") {
    afterValue = metric.customer_default ?? metric.system_default;
    afterSource = metric.customer_default !== null ? "customer" : "system";
  }
  const afterEval = change.eval ?? metric.eval;
  const after = fmt(afterValue, afterEval, withEval);
  const unchanged = afterValue === metric.value && afterSource === metric.source && afterEval === metric.eval;
  if (unchanged) {
    return { id, name, kind: "same", before, beforeSource: metric.source, after: "No change" };
  }
  const overwrite = change.action === "set" && metric.source === "resource" && metric.value !== change.value;
  return {
    id, name, kind: overwrite ? "overwrite" : "change", before, beforeSource: metric.source,
    after: `${after} ${SOURCE_LABEL[afterSource]}`,
  };
}

export function bulkUpdate(change: BulkChange, metric: ThresholdMetric): ThresholdUpdate {
  const update: ThresholdUpdate = {};
  if (change.action === "set" && change.value !== undefined) update.set = { [change.metric]: change.value };
  if (change.action === "clear") update.clear = [change.metric];
  if (change.eval !== null && !metric.eval_locked && change.eval !== metric.eval) {
    update.eval = { [change.metric]: change.eval === metric.eval_default ? null : change.eval };
  }
  return update;
}

// ── 고객사 기본값(Settings) ────────────────────────────

export interface DefaultImpact {
  /** 기본값을 따르는 리소스 — 새 값이 적용된다 */
  applies: string[];
  /** 개별값(리소스 태그)이 있어 그대로인 리소스 */
  keeps: string[];
  /** 알람을 끈 리소스, 또는 이 지표 알람이 없는 리소스 */
  skips: string[];
}

/** 고객사 기본값을 바꾸면 어느 리소스에 적용되나. 리소스 태그가 기본값보다 우선한다. */
export function defaultImpact(metricKey: string, resources: { name: string; metrics: ThresholdMetric[] }[]): DefaultImpact {
  const impact: DefaultImpact = { applies: [], keeps: [], skips: [] };
  for (const r of resources) {
    const metric = r.metrics.find((m) => m.metric === metricKey);
    if (!metric || metric.off) impact.skips.push(r.name);
    else if (metric.source === "resource") impact.keeps.push(r.name);
    else impact.applies.push(r.name);
  }
  return impact;
}

/** 값 분포 "80 × 7 · 85 × 3" */
export function distribution(values: string[]): string {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([v, c]) => `${v} × ${c}`).join(" · ");
}

/** 동시에 limit개씩 실행 — 실패는 모으고 나머지는 계속 */
export async function runPool<T>(
  items: T[],
  task: (item: T) => Promise<void>,
  limit = 3,
  onDone?: (item: T, error?: unknown) => void,
): Promise<void> {
  const queue = [...items];
  const worker = async () => {
    for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
      try {
        await task(item);
        onDone?.(item);
      } catch (error) {
        onDone?.(item, error);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
}
