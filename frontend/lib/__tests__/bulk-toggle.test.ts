import { describe, it, expect, vi } from "vitest";
import { describeBulkToggle, runBulkToggle } from "../bulk-toggle";

vi.mock("@/lib/api-functions", () => ({ toggleMonitoring: vi.fn() }));

function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("runBulkToggle", () => {
  it("partitions successes and failures without aborting the batch", async () => {
    const toggle = vi.fn(async (id: string) => {
      if (id === "bad") throw new Error("boom");
    });
    const result = await runBulkToggle(["a", "bad", "c"], true, { toggle });
    expect(result.succeeded.sort()).toEqual(["a", "c"]);
    expect(result.failed).toEqual([{ id: "bad", message: "boom" }]);
    expect(toggle).toHaveBeenCalledTimes(3);
    expect(toggle).toHaveBeenCalledWith("a", true);
  });

  it("never runs more than `concurrency` toggles at once", async () => {
    const pending = new Map<string, ReturnType<typeof deferred>>();
    let inFlight = 0;
    let maxInFlight = 0;
    const toggle = vi.fn((id: string) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      const d = deferred();
      pending.set(id, d);
      return d.promise.finally(() => { inFlight -= 1; });
    });

    const run = runBulkToggle(["1", "2", "3", "4", "5"], false, { toggle, concurrency: 2 });
    await Promise.resolve();
    expect(toggle).toHaveBeenCalledTimes(2);

    for (const id of ["1", "2", "3", "4", "5"]) {
      // 한 슬롯이 비어야 다음 항목이 시작된다
      while (!pending.has(id)) await Promise.resolve();
      pending.get(id)!.resolve();
      await Promise.resolve();
    }
    const result = await run;
    expect(result.succeeded).toHaveLength(5);
    expect(maxInFlight).toBe(2);
  });

  it("handles an empty selection", async () => {
    const toggle = vi.fn();
    expect(await runBulkToggle([], true, { toggle })).toEqual({ succeeded: [], failed: [] });
    expect(toggle).not.toHaveBeenCalled();
  });
});

describe("describeBulkToggle", () => {
  it("reports all-success, all-failed, and partial outcomes", () => {
    expect(describeBulkToggle({ succeeded: ["a", "b"], failed: [] }, true)).toEqual({
      kind: "success",
      message: "2개 리소스의 모니터링을 활성화했습니다.",
    });
    expect(describeBulkToggle({ succeeded: [], failed: [{ id: "a", message: "x" }] }, false).kind).toBe("error");
    const partial = describeBulkToggle(
      { succeeded: ["a"], failed: [{ id: "b", message: "x" }, { id: "c", message: "y" }] },
      false,
    );
    expect(partial.kind).toBe("error");
    expect(partial.message).toContain("1개 비활성화, 2개 실패: b, c");
  });
});
