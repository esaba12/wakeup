import { useState } from "react";
import { api, ApiError } from "../api/client";
import { ProgressRing } from "../components/ProgressRing";
import type { AppState } from "../types";
import { formatDurationShort } from "../utils/format";

const ACTIVE_STATES = new Set(["WINDDOWN", "ASLEEP", "SUNRISE", "ALARM", "SNOOZE", "AWAKE"]);
const SNOOZE_STATES = new Set(["SUNRISE", "ALARM"]);
const DISMISS_STATES = new Set(["SUNRISE", "ALARM", "SNOOZE"]);

const STATE_LABEL: Record<string, string> = {
  IDLE: "Idle",
  WINDDOWN: "Winding down",
  ASLEEP: "Asleep",
  SUNRISE: "Sunrise",
  ALARM: "Alarm",
  SNOOZE: "Snoozed",
  AWAKE: "Awake",
};

export function NowScreen({ state }: { state: AppState | null }): JSX.Element {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (state === null) {
    return (
      <div className="screen">
        <div className="empty-state">Waiting for the device…</div>
      </div>
    );
  }

  const routine = state.routine;
  const isActive = routine.id !== null && ACTIVE_STATES.has(routine.state);
  const canSnooze = isActive && SNOOZE_STATES.has(routine.state);
  const canDismiss = isActive && DISMISS_STATES.has(routine.state);

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="screen">
      <div className="now-hero">
        <ProgressRing
          progress={routine.progress}
          stateLabel={STATE_LABEL[routine.state] ?? routine.state}
          stepLabel={routine.id === null ? "Nothing scheduled" : routine.step}
        />
      </div>

      {error && <p className="banner">{error}</p>}

      {isActive ? (
        <div className="btn-row">
          {canSnooze && (
            <button
              type="button"
              className="btn btn--primary btn--big btn--block"
              disabled={busy !== null}
              onClick={() => run("snooze", api.snooze)}
            >
              {busy === "snooze" ? "Snoozing…" : "Snooze"}
            </button>
          )}
          {canDismiss && (
            <button
              type="button"
              className="btn btn--big btn--block"
              disabled={busy !== null}
              onClick={() => run("dismiss", api.dismiss)}
            >
              {busy === "dismiss" ? "…" : "Dismiss"}
            </button>
          )}
          {!canSnooze && !canDismiss && (
            <button
              type="button"
              className="btn btn--danger btn--big btn--block"
              disabled={busy !== null}
              onClick={() => run("stop", api.stopRoutine)}
            >
              {busy === "stop" ? "Stopping…" : routine.state === "AWAKE" ? "Back to Now" : "Stop"}
            </button>
          )}
        </div>
      ) : (
        <p className="next-alarm-line">
          {state.next_alarm === null ? (
            <>No alarm set</>
          ) : (
            <>
              Next alarm in <strong>{formatDurationShort(state.next_alarm.in_s)}</strong>
              {state.next_alarm.skipped ? " (skipped tomorrow)" : ""}
            </>
          )}
        </p>
      )}

      <div className="card stack">
        <span className="muted">Quick light</span>
        <div className="shortcut-row">
          <button
            type="button"
            className="btn"
            disabled={busy !== null}
            onClick={() => run("nightlight", () => api.lightPreset("nightlight"))}
          >
            Nightlight
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy !== null}
            onClick={() => run("reading", () => api.lightPreset("reading"))}
          >
            Reading
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy !== null}
            onClick={() => run("off", () => api.lightPreset("off"))}
          >
            Off
          </button>
        </div>
      </div>

      <div className="card row">
        <span className="muted">Light</span>
        <span>
          {state.light.reachable
            ? state.light.on
              ? `${Math.round(state.light.brightness * 100)}%${
                  state.light.cct ? ` · ${state.light.cct}K` : ""
                }`
              : "Off"
            : "Unreachable"}
        </span>
      </div>
      <div className="card row">
        <span className="muted">Audio</span>
        <span>{state.audio.playing ?? "Silent"}</span>
      </div>
    </div>
  );
}
