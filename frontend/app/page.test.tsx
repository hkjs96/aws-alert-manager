import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import HomePage from "./page";

describe("HomePage", () => {
  it("renders the Alarm Manager heading", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("heading", { name: /alarm manager/i }),
    ).toBeInTheDocument();
  });

  it("renders the description text", () => {
    render(<HomePage />);
    expect(
      screen.getByText(/aws cloudwatch alarm management dashboard/i),
    ).toBeInTheDocument();
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
