import { describe, expect, it } from "vitest";
import type { Routine } from "../types";
import { OPEN_ENDED_WIDTH_S, layoutRoutineTimeline, stepAudioLevel, stepBrightness } from "./timeline";

function baseRoutine(steps: Routine["steps"]): Routine {
  return {
    version: 1,
    name: "Test",
    id: "test",
    trigger: { type: "alarm", ref: "a1" },
    steps,
  };
}

describe("layoutRoutineTimeline", () => {
  it("chains duration-based steps sequentially from t=0", () => {
    const routine = baseRoutine([
      { id: "dim", duration: "10m" },
      { id: "off", duration: "20m" },
    ]);
    const { totalS, segments } = layoutRoutineTimeline(routine);
    expect(segments).toHaveLength(2);
    expect(segments[0]).toMatchObject({ startS: 0, widthS: 600 });
    expect(segments[1]).toMatchObject({ startS: 600, widthS: 1200 });
    expect(totalS).toBe(1800);
  });

  it("gives until_cancel/until_next_step steps a nominal open-ended width", () => {
    const routine = baseRoutine([{ id: "sleep", duration: "until_cancel" }]);
    const { segments } = layoutRoutineTimeline(routine);
    expect(segments[0]).toMatchObject({ kind: "open-ended", widthS: OPEN_ENDED_WIDTH_S });
  });

  it("anchors at_offset steps to the end of the duration chain, offset by their own duration", () => {
    const routine = baseRoutine([
      { id: "ramp", duration: "30m" },
      { id: "chime", at_offset: "-3m" },
    ]);
    const { segments } = layoutRoutineTimeline(routine);
    const chime = segments.find((s) => s.step.id === "chime");
    // chain end is 30m = 1800s; -3m = -180s -> starts at 1620s, overlapping the tail.
    expect(chime?.startS).toBe(1620);
    expect(chime?.kind).toBe("offset-marker");
  });

  it("never lets an at_offset step land before t=0", () => {
    const routine = baseRoutine([{ id: "early", at_offset: "-999h" }]);
    const { segments } = layoutRoutineTimeline(routine);
    expect(segments[0].startS).toBe(0);
  });
});

describe("stepBrightness", () => {
  it("reads an explicit target over a curve reference", () => {
    expect(stepBrightness({ id: "s", light: { brightness: 0.4 } })).toBe(0.4);
    expect(stepBrightness({ id: "s", light: { to: { brightness: 0.7 } } })).toBe(0.7);
  });
  it("treats an 'off' light block as brightness 0", () => {
    expect(stepBrightness({ id: "s", light: { off: true } })).toBe(0);
  });
  it("returns null when the step doesn't touch the light", () => {
    expect(stepBrightness({ id: "s" })).toBeNull();
  });
});

describe("stepAudioLevel", () => {
  it("normalizes a gain_db to 0..1", () => {
    expect(stepAudioLevel({ id: "s", audio: { gain_db: -60 } })).toBe(0);
    expect(stepAudioLevel({ id: "s", audio: { gain_db: 0 } })).toBe(1);
  });
  it("treats an explicit stop as level 0", () => {
    expect(stepAudioLevel({ id: "s", audio: { stop: true } })).toBe(0);
  });
});
