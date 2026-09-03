import { describe, expect, it } from "vitest";
import type { AppState } from "../types";
import { applyServerMessage, parseServerMessage } from "./wsProtocol";

function makeState(overrides: Partial<AppState> = {}): AppState {
  return {
    clock: { now: "2026-09-03T22:00:00-04:00", tz: "America/Detroit", synced: true, source: "ntp" },
    routine: {
      id: null,
      state: "IDLE",
      step: null,
      started_at: null,
      trigger_at: null,
      progress: null,
    },
    light: { id: "mock", reachable: true, on: false, brightness: 0, cct: null },
    audio: { output: "mock", available: true, playing: null, gain_db: -60 },
    next_alarm: null,
    health: "ok",
    ...overrides,
  };
}

describe("applyServerMessage", () => {
  it("a 'state' frame fully replaces whatever was there before", () => {
    const initial = makeState({ health: "degraded" });
    const fresh = makeState({ health: "ok" });
    const result = applyServerMessage(initial, { type: "state", data: fresh });
    expect(result).toEqual(fresh);
  });

  it("a 'delta' frame merges only the top-level keys it carries", () => {
    const current = makeState();
    const result = applyServerMessage(current, {
      type: "delta",
      data: { health: "degraded" },
    });
    expect(result).toEqual({ ...current, health: "degraded" });
    // sibling keys untouched by reference
    expect(result?.light).toBe(current.light);
  });

  it("a 'delta' before any 'state' frame is dropped, not guessed at", () => {
    const result = applyServerMessage(null, { type: "delta", data: { health: "ok" } });
    expect(result).toBeNull();
  });

  it("ack/error frames never change the state snapshot", () => {
    const current = makeState();
    const result = applyServerMessage(current, {
      type: "ack",
      action: "snooze",
      data: { snoozed: true },
    });
    expect(result).toBe(current);
  });
});

describe("parseServerMessage", () => {
  it("parses a well-formed frame", () => {
    const raw = JSON.stringify({ type: "delta", data: { health: "ok" } });
    expect(parseServerMessage(raw)).toEqual({ type: "delta", data: { health: "ok" } });
  });

  it("returns null for malformed JSON instead of throwing", () => {
    expect(parseServerMessage("{not json")).toBeNull();
  });

  it("returns null for a frame with no 'type'", () => {
    expect(parseServerMessage(JSON.stringify({ data: {} }))).toBeNull();
  });
});
