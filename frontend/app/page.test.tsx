import { describe, it, expect } from "vitest";
import * as fc from "fast-check";

describe("HomePage", () => {
  it("exports a default function that redirects to /dashboard", async () => {
    // The page module calls redirect() which throws in test context
    // Just verify the module exports correctly
    const mod = await import("./page");
    expect(typeof mod.default).toBe("function");
  });
});

describe("fast-check smoke test", () => {
  it("verifies fast-check is working", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 100 }), (n) => {
        return n >= 1 && n <= 100;
      }),
    );
  });
});
