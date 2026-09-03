import { describe, expect, it } from "vitest";
import { formatDays, formatDurationShort } from "./format";

describe("formatDurationShort", () => {
  it("renders hours and minutes for a long duration", () => {
    expect(formatDurationShort(8 * 3600 + 12 * 60)).toBe("8h 12m");
  });
  it("renders minutes and seconds under an hour", () => {
    expect(formatDurationShort(90)).toBe("1m 30s");
  });
  it("renders bare seconds under a minute", () => {
    expect(formatDurationShort(45)).toBe("45s");
  });
});

describe("formatDays", () => {
  it("labels an empty set as one-time — the absence of a schedule must read as one-time, not blank", () => {
    expect(formatDays([])).toBe("One-time");
  });
  it("recognizes weekdays and weekends as named shortcuts", () => {
    expect(formatDays([1, 2, 3, 4, 5])).toBe("Weekdays");
    expect(formatDays([6, 7])).toBe("Weekends");
    expect(formatDays([1, 2, 3, 4, 5, 6, 7])).toBe("Every day");
  });
  it("falls back to a day list for anything else", () => {
    expect(formatDays([2, 4])).toBe("Tue, Thu");
  });
});
