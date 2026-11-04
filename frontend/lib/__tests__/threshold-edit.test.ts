import { describe, it, expect } from "vitest";
import { buildUpdate, bulkUpdate, defaultImpact, evalMeaning, impactFor, initialDraft, parseEval, runPool } from "@/lib/threshold-edit";
import type { ThresholdMetric } from "@/types/api";

const CPU: ThresholdMetric = {
  metric: "CPUUtilization", label: "CPU", direction: ">", unit: "%", statistic: "Average", period: 300,
  off: false, value: 80, source: "system", customer_default: null, system_default: 80,
  eval: "2/3", eval_source: "system", eval_default: "2/3", eval_locked: false,
};

describe("판단 방식", () => {
  it("M/N을 검증한다", () => {
    expect(parseEval("3/5")).toEqual({ m: 3, n: 5 });
    expect(parseEval("5/3")).toBeNull();
    expect(parseEval("1/11")).toBeNull();
  });

  it("뜻을 풀어 쓴다", () => {
    expect(evalMeaning("3/5", 300, 90, "%", ">")).toBe("최근 25분 중 15분 이상 90 %를 넘으면 알람");
    expect(evalMeaning("1/1", 60, null, "", ">")).toBe("한 번만 넘으면 바로 알람");
  });
});

describe("단일 편집 본문", () => {
  it("바꾼 것만 보낸다", () => {
    const draft = { ...initialDraft(CPU), value: "90", eval: "3/5" };
    expect(buildUpdate([CPU], { CPUUtilization: draft })).toEqual({ set: { CPUUtilization: 90 }, eval: { CPUUtilization: "3/5" }, clear: [] });
    expect(buildUpdate([CPU], { CPUUtilization: initialDraft(CPU) })).toEqual({ set: {}, eval: {}, clear: [] });
  });

  it("기본 판단 방식으로 돌리면 태그를 지운다(null)", () => {
    const custom = { ...CPU, eval: "3/5", eval_source: "resource" as const };
    expect(buildUpdate([custom], { CPUUtilization: { ...initialDraft(custom), eval: "2/3" } }).eval).toEqual({ CPUUtilization: null });
  });

  it("잘못된 값은 막는다", () => {
    expect(() => buildUpdate([CPU], { CPUUtilization: { ...initialDraft(CPU), value: "-1" } })).toThrow();
  });
});

describe("벌크 영향", () => {
  const change = { metric: "CPUUtilization", action: "set" as const, value: 90, eval: "3/5" };

  it("바뀜 / 덮어씀 / 같음 / 건너뜀", () => {
    expect(impactFor("a", "a", CPU, change).kind).toBe("change");
    expect(impactFor("b", "b", { ...CPU, value: 95, source: "resource" }, change).kind).toBe("overwrite");
    expect(impactFor("c", "c", { ...CPU, value: 90, source: "resource", eval: "3/5" }, change).kind).toBe("same");
    expect(impactFor("d", "d", { ...CPU, off: true, value: null }, change).kind).toBe("skip");
    expect(impactFor("e", "e", undefined, change).kind).toBe("skip");
  });

  it("해제는 고객사 기본값으로 돌아간다", () => {
    const row = impactFor("a", "a", { ...CPU, value: 95, source: "resource", customer_default: 85 },
      { metric: "CPUUtilization", action: "clear", eval: null });
    expect(row.after).toBe("85 고객사 기본");
  });

  it("리소스별 본문", () => {
    expect(bulkUpdate(change, CPU)).toEqual({ set: { CPUUtilization: 90 }, eval: { CPUUtilization: "3/5" } });
  });
});

describe("runPool", () => {
  it("동시 실행 수를 지키고 실패를 모은다", async () => {
    let active = 0;
    let peak = 0;
    const done: [number, boolean][] = [];
    await runPool([1, 2, 3, 4, 5, 6, 7], async (n) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 5));
      active -= 1;
      if (n === 4) throw new Error("boom");
    }, 3, (n, e) => done.push([n, !e]));
    expect(peak).toBe(3);
    expect(done).toHaveLength(7);
    expect(done.find(([n]) => n === 4)?.[1]).toBe(false);
  });
});

describe("고객사 기본값 영향", () => {
  it("개별값은 유지, 끈 알람·없는 지표는 건너뛴다", () => {
    const result = defaultImpact("CPUUtilization", [
      { name: "a", metrics: [CPU] },
      { name: "b", metrics: [{ ...CPU, source: "customer", customer_default: 85, value: 85 }] },
      { name: "c", metrics: [{ ...CPU, source: "resource", value: 95 }] },
      { name: "d", metrics: [{ ...CPU, off: true }] },
      { name: "e", metrics: [] },
    ]);
    expect(result).toEqual({ applies: ["a", "b"], keeps: ["c"], skips: ["d", "e"] });
  });
});