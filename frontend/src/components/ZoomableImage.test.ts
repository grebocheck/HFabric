import { describe, expect, it } from "vitest";

import { clampScale, MAX_SCALE, MIN_SCALE } from "./ZoomableImage";

describe("clampScale", () => {
  it("keeps scale within [MIN, MAX]", () => {
    expect(clampScale(0.1)).toBe(MIN_SCALE);
    expect(clampScale(999)).toBe(MAX_SCALE);
    expect(clampScale(2.5)).toBe(2.5);
  });

  it("treats the bounds as inclusive", () => {
    expect(clampScale(MIN_SCALE)).toBe(MIN_SCALE);
    expect(clampScale(MAX_SCALE)).toBe(MAX_SCALE);
  });
});
