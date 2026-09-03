import yaml from "js-yaml";
import { describe, expect, it } from "vitest";
import type { Routine } from "../types";
import { dumpRoutine, normalizeRoutine } from "./routineYaml";

/** A `GET /api/routines/{id}` response shaped exactly like the real bug
 * observed against a running daemon: every `timedelta` field comes back as
 * an ISO-8601 duration (`PT30M`, `-PT3M`) instead of the compact form
 * `core/routines.py::parse_duration` and `routines/schema.json` expect. */
const rawFromServer: Routine = {
  version: 1,
  name: "Weekday wake",
  id: "weekday-wake",
  trigger: { type: "alarm", ref: "alarm_morning" },
  steps: [
    {
      id: "sunrise",
      duration: "PT30M",
      light: { curve: "sunrise-classic", to: { brightness: 0.9, cct: 4500 }, transition: "PT2M" },
      on_cancel: { light: { off: true } },
    },
    {
      id: "chime",
      at_offset: "-PT3M",
      audio: { source: "file:chimes/windchime.flac", ramp_to_db: -14, over: "PT4M" },
      escalate_after: "PT1M",
    },
  ],
  snooze: { duration: "PT9M", max: 3, light: { hold: true }, audio: { stop: true } },
};

describe("normalizeRoutine", () => {
  it("converts every ISO-8601 duration field back to the compact grammar", () => {
    const normalized = normalizeRoutine(rawFromServer);
    expect(normalized.steps[0].duration).toBe("30m");
    expect(normalized.steps[0].light?.transition).toBe("2m");
    expect(normalized.steps[1].at_offset).toBe("-3m");
    expect(normalized.steps[1].audio?.over).toBe("4m");
    expect(normalized.steps[1].escalate_after).toBe("1m");
    expect(normalized.snooze?.duration).toBe("9m");
  });

  it("leaves non-duration fields alone", () => {
    const normalized = normalizeRoutine(rawFromServer);
    expect(normalized.steps[0].light?.curve).toBe("sunrise-classic");
    expect(normalized.steps[1].audio?.source).toBe("file:chimes/windchime.flac");
  });
});

describe("dumpRoutine (works around core/routines.py rejecting explicit `key: null`)", () => {
  it("omits null-valued optional fields entirely rather than emitting `key: null`", () => {
    // Shaped like a real GET /api/routines/{id} response: every optional
    // field Pydantic's model_dump includes explicitly as null.
    const routine: Routine = {
      version: 1,
      name: "Weekday wake",
      id: "weekday-wake",
      trigger: { type: "alarm", ref: "alarm_morning", at: null, days: null },
      steps: [
        {
          id: "sunrise",
          duration: "30m",
          at_offset: null,
          ends_at: "trigger",
          light: {
            curve: "sunrise-classic",
            to: { brightness: 0.9, cct: 4500 },
            brightness: null,
            cct: null,
            transition: null,
            off: null,
            hold: null,
            reverse: false,
          },
          audio: null,
          on_cancel: null,
          escalate_after: null,
        },
      ],
      snooze: null,
    };

    const text = dumpRoutine(routine);
    expect(text).not.toMatch(/:\s*null/);

    // And the result parses back into something that still has exactly the
    // meaningful fields (nothing was lost besides the nulls).
    const parsed = yaml.load(text) as any;
    expect(parsed.steps[0]).not.toHaveProperty("audio");
    expect(parsed.steps[0]).not.toHaveProperty("on_cancel");
    expect(parsed.steps[0].light).not.toHaveProperty("brightness");
    expect(parsed.steps[0].light.reverse).toBe(false); // a real `false`, not pruned
    expect(parsed).not.toHaveProperty("snooze");
    expect(parsed.steps[0].light.curve).toBe("sunrise-classic");
  });
});
