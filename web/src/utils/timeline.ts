import type { Routine, RoutineStep } from "../types";
import { parseDurationSeconds } from "./duration";

/**
 * Pure layout math for the Routines screen's timeline bar, kept separate
 * from rendering so it's unit-testable without touching the DOM.
 *
 * This is a *static* visualization of the routine's own YAML — it never
 * touches a live run's server-computed `progress` (docs/07's "no
 * client-side derived state" is about the live clock, not about laying
 * out an editor preview of a config file).
 *
 * Known gap: neither `docs/07-api-and-state.md`'s REST list nor
 * `routines/schema.json` exposes the actual curve keyframes a `light.curve`
 * reference points at (they live server-side under `curves/`, with no
 * `GET /api/curves/{id}`), so a step that ramps via a named curve can only
 * be drawn as a generic ramp gradient here, not the curve's real shape.
 * Flagged in the task report as a spec/API gap for a follow-up task.
 */

export const OPEN_ENDED_WIDTH_S = 180; // nominal width for until_cancel/until_next_step
const AT_OFFSET_MARKER_WIDTH_S = 60;

export type SegmentKind = "duration" | "open-ended" | "offset-marker";

export interface TimelineSegment {
  step: RoutineStep;
  kind: SegmentKind;
  startS: number;
  widthS: number;
}

export interface TimelineLayout {
  totalS: number;
  segments: TimelineSegment[];
}

export function layoutRoutineTimeline(routine: Routine): TimelineLayout {
  const segments: TimelineSegment[] = [];
  let cursor = 0;

  // Pass 1: sequential duration-based steps chain from t=0.
  for (const step of routine.steps) {
    if (step.at_offset !== null && step.at_offset !== undefined) continue;
    if (step.duration === "until_cancel" || step.duration === "until_next_step") {
      segments.push({ step, kind: "open-ended", startS: cursor, widthS: OPEN_ENDED_WIDTH_S });
      cursor += OPEN_ENDED_WIDTH_S;
      continue;
    }
    const width =
      typeof step.duration === "string" ? parseDurationSeconds(step.duration) ?? 0 : 0;
    segments.push({ step, kind: "duration", startS: cursor, widthS: Math.max(width, 1) });
    cursor += Math.max(width, 0);
  }

  const chainEnd = cursor;

  // Pass 2: at_offset steps anchor to the trigger instant. Absent a live
  // run, the trigger is assumed to land at the end of the duration chain
  // (the common "ramp finishes right as the alarm fires" shape) — offsets
  // are usually negative or small positive from there.
  for (const step of routine.steps) {
    if (step.at_offset === null || step.at_offset === undefined) continue;
    const offsetS = parseDurationSeconds(step.at_offset) ?? 0;
    const startS = Math.max(0, chainEnd + offsetS);
    segments.push({ step, kind: "offset-marker", startS, widthS: AT_OFFSET_MARKER_WIDTH_S });
  }

  const totalS = Math.max(
    1,
    ...segments.map((s) => s.startS + s.widthS),
    chainEnd
  );

  segments.sort((a, b) => a.startS - b.startS);
  return { totalS, segments };
}

/** 0 (near-off) .. 1 (bright) best-effort target brightness for a step's
 * light block, purely for the timeline's fill color — `null` when the
 * step doesn't touch the light at all. */
export function stepBrightness(step: RoutineStep): number | null {
  const light = step.light;
  if (light === null || light === undefined) return null;
  if (light.off) return 0;
  if (typeof light.brightness === "number") return light.brightness;
  if (light.to && typeof light.to.brightness === "number") return light.to.brightness;
  if (light.curve) return 0.6; // unknown shape; see module docstring
  if (light.hold) return 0.4;
  return null;
}

/** -60..0 dB best-effort audio level for a step, normalized to 0..1. */
export function stepAudioLevel(step: RoutineStep): number | null {
  const audio = step.audio;
  if (audio === null || audio === undefined) return null;
  if (audio.stop) return 0;
  const db = audio.ramp_to_db ?? audio.gain_db;
  if (typeof db === "number") return Math.max(0, Math.min(1, (db + 60) / 60));
  if (audio.source) return 0.5;
  return null;
}
