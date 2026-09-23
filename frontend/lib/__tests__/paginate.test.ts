import { describe, expect, it, vi } from "vitest";

import { collectAllPages, type Page } from "@/lib/paginate";

function server(total: number, pageSize: number) {
  const all = Array.from({ length: total }, (_, i) => ({ id: `r-${i}` }));
  return vi.fn(async (page: number): Promise<Page<{ id: string }>> => ({
    items: all.slice((page - 1) * pageSize, page * pageSize),
    total,
  }));
}

describe("collectAllPages", () => {
  it("returns every item across pages — 266 resources used to show as 100", async () => {
    const fetchPage = server(266, 100);
    const items = await collectAllPages(fetchPage, 100, (r) => r.id);
    expect(items).toHaveLength(266);
    expect(fetchPage).toHaveBeenCalledTimes(3);
    expect(new Set(items.map((r) => r.id)).size).toBe(266);
  });

  it("makes one call when everything fits on the first page", async () => {
    const fetchPage = server(42, 100);
    expect(await collectAllPages(fetchPage, 100, (r) => r.id)).toHaveLength(42);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("handles an empty list", async () => {
    const fetchPage = server(0, 100);
    expect(await collectAllPages(fetchPage, 100, (r) => r.id)).toEqual([]);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("folds an item that shows up on two pages", async () => {
    const fetchPage = vi.fn(async (page: number) => ({
      items: page === 1 ? [{ id: "a" }, { id: "b" }] : [{ id: "b" }, { id: "c" }],
      total: 4,
    }));
    expect((await collectAllPages(fetchPage, 2, (r) => r.id)).map((r) => r.id)).toEqual(["a", "b", "c"]);
  });

  it("stops at the page cap instead of calling forever", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchPage = server(1000, 10);
    const items = await collectAllPages(fetchPage, 10, (r) => r.id, 5);
    expect(fetchPage).toHaveBeenCalledTimes(5);
    expect(items).toHaveLength(50);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
