import { describe, expect, it } from "vitest";
import { isValidDuration, isoDurationToSeconds, parseDurationSeconds, toCompactDuration } from "./duration";

describe("parseDurationSeconds (mirrors core/routines.py::parse_duration)", () => {
  it.each([
    ["30m", 1800],
    ["90s", 90],
    ["1h", 3600],
    ["-3m", -180],
    ["0s", 0],
  ])("parses %s -> %i seconds", (input, expected) => {
    expect(parseDurationSeconds(input)).toBe(expected);
  });

  it.each(["1h30m", "5", "5x", "", "PT5M", " 5m"])("rejects %s", (input) => {
    expect(parseDurationSeconds(input)).toBeNull();
    expect(isValidDuration(input)).toBe(false);
  });
});

describe("toCompactDuration (works around GET/PUT /api/routines returning ISO-8601)", () => {
  it("leaves the domain's own compact form untouched", () => {
    expect(toCompactDuration("30m")).toBe("30m");
    expect(toCompactDuration("-3m")).toBe("-3m");
  });

  it.each([
    ["PT30M", "30m"],
    ["-PT3M", "-3m"],
    ["PT1H", "1h"],
    ["PT90S", "90s"],
    ["PT1H30M", "90m"], // 5400s divides evenly by 60 -> minutes, the largest clean unit
  ])("converts the ISO-8601 form %s the server actually sends -> %s", (iso, expected) => {
    expect(toCompactDuration(iso)).toBe(expected);
  });

  it("passes through values that are neither grammar (until_cancel, etc.)", () => {
    expect(toCompactDuration("until_cancel")).toBe("until_cancel");
    expect(toCompactDuration("until_next_step")).toBe("until_next_step");
  });
});

describe("isoDurationToSeconds", () => {
  it("returns null for a bare 'P' (not a real duration) or garbage", () => {
    expect(isoDurationToSeconds("P")).toBeNull();
    expect(isoDurationToSeconds("nonsense")).toBeNull();
  });
});
