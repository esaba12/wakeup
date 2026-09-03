import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AppState } from "../types";
import { NowScreen } from "./NowScreen";

function makeState(overrides: Partial<AppState> = {}): AppState {
  return {
    clock: { now: "2026-09-03T22:00:00-04:00", tz: "America/Detroit", synced: true, source: "ntp" },
    routine: { id: null, state: "IDLE", step: null, started_at: null, trigger_at: null, progress: null },
    light: { id: "mock", reachable: true, on: false, brightness: 0, cct: null },
    audio: { output: "mock", available: true, playing: null, gain_db: -60 },
    next_alarm: null,
    health: "ok",
    ...overrides,
  };
}

describe("NowScreen", () => {
  it("makes the absence of an alarm explicit rather than blank", () => {
    render(<NowScreen state={makeState({ next_alarm: null })} />);
    expect(screen.getByText("No alarm set")).toBeInTheDocument();
  });

  it("shows the server-provided countdown when an alarm is set", () => {
    render(
      <NowScreen
        state={makeState({
          next_alarm: { id: "a1", at: "2026-09-04T06:40:00-04:00", in_s: 30117, skipped: false },
        })}
      />
    );
    expect(screen.getByText(/Next alarm in/)).toBeInTheDocument();
    expect(screen.getByText("8h 21m")).toBeInTheDocument();
  });

  it("shows Stop instead of the countdown while a routine is active", () => {
    render(
      <NowScreen
        state={makeState({
          routine: {
            id: "winddown",
            state: "WINDDOWN",
            step: "dim",
            started_at: "2026-09-03T22:00:00-04:00",
            trigger_at: null,
            progress: 0.4,
          },
        })}
      />
    );
    expect(screen.queryByText(/No alarm set/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
  });

  it("offers Snooze during SUNRISE (dismiss-for-today semantics live server-side)", () => {
    render(
      <NowScreen
        state={makeState({
          routine: {
            id: "weekday-wake",
            state: "SUNRISE",
            step: "sunrise",
            started_at: "2026-09-04T06:10:00-04:00",
            trigger_at: "2026-09-04T06:40:00-04:00",
            progress: 0.2,
          },
        })}
      />
    );
    expect(screen.getByRole("button", { name: /snooze/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
  });
});
