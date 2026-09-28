import { describe, expect, it } from "vitest";

import { outcomeTone } from "./outcome";

describe("outcomeTone", () => {
  it.each([
    ["CONFIRMED", "success"],
    ["BOOKED", "success"],
    ["TRANSFERRED", "warning"],
    ["UNREACHABLE", "danger"],
    [null, "info"],
  ] as const)("%s → %s", (outcome, tone) => {
    expect(outcomeTone(outcome)).toBe(tone);
  });
});
