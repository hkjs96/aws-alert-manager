import type { ThresholdMetric, ThresholdSource, ThresholdUpdate } from "@/types/api";

/** 판단 방식 선택지 — 그 밖의 값은 "직접 입력" */
export const EVAL_PRESETS = ["1/1", "2/3", "3/5"] as const;

export const SOURCE_LABEL: Record<ThresholdSource, string> = {
  resource: "개별값",
  customer: "고객사 기본",
  system: "시스템 기본",
};

export function parseEval(value: string): { m: number; n: number } | null {
  const match = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(value);
  if (!match) return null;
  const m = Number(match[1]);
  const n = Number(match[2]);
  return m >= 1 && m <= n && n <= 10 ? { m, n } : null;
}

function minutes(seconds: number): string {
  return seconds % 60 === 0 ? `${seconds / 60}분` : `${seconds}초`;
}

/** "최근 25분 중 15분 이상 90 %를 넘으면 알람" */
export function evalMeaning(evalValue: string, period: number | null, value: number | null, unit: string, direction: string): string {
  const parsed = parseEval(evalValue);
  const p = period ?? 300;
  const verb = direction.startsWith("<") ? "아래로 내려가면" : "넘으면";
  const target = value === null ? "" : ` ${value}${unit ? ` ${unit}` : ""}를`;
  if (!parsed || (parsed.m === 1 && parsed.n === 1)) {
    return `한 번만${target} ${verb} 바로 알람`;
  }
  return `최근 ${minutes(parsed.n * p)} 중 ${minutes(parsed.m * p)} 이상${target} ${verb} 알람`;
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
      if (!Number.isFinite(value) || value <= 0) throw new Error(`${metric.label}: 0보다 큰 숫자를 넣으세요`);
      if (value !== metric.value || metric.source !== "resource") update.set[metric.metric] = value;
    }
    if (!metric.eval_locked && draft.eval !== metric.eval) {
      if (!parseEval(draft.eval)) throw new Error(`${metric.label}: 판단 방식은 M/N (1 ≤ M ≤ N ≤ 10)`);
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
    return { id, name, kind: "skip", before: "—", beforeSource: "system", after: "건너뜀", reason: "이 지표의 알람이 없습니다" };
  }
  const before = fmt(metric.value, metric.eval, withEval);
  if (metric.off) {
    return { id, name, kind: "skip", before: "off", beforeSource: metric.source, after: "건너뜀", reason: "끈 알람은 그대로" };
  }
  if (withEval && metric.eval_locked) {
    return { id, name, kind: "skip", before, beforeSource: metric.source, after: "건너뜀", reason: "판단 방식이 고정된 지표" };
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
    return { id, name, kind: "same", before, beforeSource: metric.source, after: "변화 없음" };
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
