import { describe, it, expect } from "vitest";
import { timeToFrame, frameToTime, clampTime } from "../time";

describe("timeToFrame", () => {
  it("rounds to nearest", () => {
    expect(timeToFrame(0.0, 30)).toBe(0);
    expect(timeToFrame(1.0, 30)).toBe(30);
    expect(timeToFrame(1.0 / 30 + 0.0001, 30)).toBe(1);
  });
});

describe("frameToTime", () => {
  it("is the right inverse of timeToFrame at exact frame boundaries", () => {
    for (let f = 0; f < 100; f++) {
      expect(timeToFrame(frameToTime(f, 30), 30)).toBe(f);
    }
  });
});

describe("clampTime", () => {
  it("clamps below 0 and above duration", () => {
    expect(clampTime(-1, 10)).toBe(0);
    expect(clampTime(0, 10)).toBe(0);
    expect(clampTime(5, 10)).toBe(5);
    expect(clampTime(10, 10)).toBe(10);
    expect(clampTime(11, 10)).toBe(10);
  });
});
