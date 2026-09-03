import yaml from "js-yaml";
import type { JsonSchema, ValidationError } from "./schema";
import { validateRoutine } from "./schema";
import type { AudioBlock, LightBlock, Routine, RoutineStep, SnoozeBlock } from "../types";
import { toCompactDuration } from "../utils/duration";

let cachedSchema: JsonSchema | null = null;

/** `routines/schema.json` (task 05) is copied to `web/public/routine-schema.json`
 * at build time and fetched at runtime — see that file's header comment
 * for why (no REST endpoint in docs/07 serves it, and this task's ground
 * rules say not to add one). Keep the copy in sync by hand if the schema
 * changes. */
export async function loadRoutineSchema(): Promise<JsonSchema> {
  if (cachedSchema !== null) return cachedSchema;
  const res = await fetch("/routine-schema.json");
  cachedSchema = (await res.json()) as JsonSchema;
  return cachedSchema;
}

export interface YamlParseResult {
  data: unknown;
  errors: ValidationError[];
}

export function parseYamlText(text: string): { data: unknown } | { error: string } {
  try {
    const data = yaml.load(text);
    return { data };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

export async function validateRoutineYamlText(text: string): Promise<YamlParseResult> {
  const parsed = parseYamlText(text);
  if ("error" in parsed) {
    return { data: null, errors: [{ path: "$", message: parsed.error }] };
  }
  const schema = await loadRoutineSchema();
  return { data: parsed.data, errors: validateRoutine(schema, parsed.data) };
}

/**
 * Deep-drops any object key whose value is `null` (recursing into nested
 * objects/arrays; `false`, `0`, and `""` are left alone — only `null`
 * itself is pruned). Needed because `core/routines.py::_validate_routine_yaml_shape`
 * (`_check_mapping_keys`/`_find_value`) treats an explicit `light: null` /
 * `audio: null` / `on_cancel: null` key as "present but not a mapping" and
 * hard-rejects it with "expected a mapping", rather than treating it the
 * same as the key being absent — which is exactly what a hand-authored
 * routine YAML file does (it never writes `audio: null`; it just omits the
 * key). Every `GET /api/routines/{id}` response *does* explicitly write
 * those nulls (Pydantic's `model_dump` includes every optional field), so
 * without this, fetching a routine and PUTting it straight back — the
 * YAML editor's and the form editor's entire round trip — always fails.
 * A real `core/routines.py` bug, flagged in the task report and worked
 * around here rather than fixed there (out of this task's scope).
 */
function pruneNulls<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => pruneNulls(item)) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, v] of Object.entries(value as Record<string, unknown>)) {
      if (v !== null) result[key] = pruneNulls(v);
    }
    return result as T;
  }
  return value;
}

export function dumpRoutine(routine: Routine): string {
  return yaml.dump(pruneNulls(routine), { noRefs: true, lineWidth: 100 });
}

const dur = (value: string | null | undefined): typeof value =>
  value == null ? value : toCompactDuration(value);

function normalizeLightBlock(light: LightBlock | null | undefined): LightBlock | null | undefined {
  return light == null ? light : { ...light, transition: dur(light.transition) };
}

function normalizeAudioBlock(audio: AudioBlock | null | undefined): AudioBlock | null | undefined {
  return audio == null
    ? audio
    : {
        ...audio,
        over: dur(audio.over),
        fade_in: dur(audio.fade_in),
        fade_out: dur(audio.fade_out),
        sleep_timer: dur(audio.sleep_timer),
      };
}

function normalizeStep(step: RoutineStep): RoutineStep {
  return {
    ...step,
    duration:
      step.duration === "until_cancel" || step.duration === "until_next_step" || step.duration == null
        ? step.duration
        : toCompactDuration(step.duration),
    at_offset: dur(step.at_offset),
    escalate_after: dur(step.escalate_after),
    light: normalizeLightBlock(step.light),
    audio: normalizeAudioBlock(step.audio),
    on_cancel: step.on_cancel == null
      ? step.on_cancel
      : {
          light: normalizeLightBlock(step.on_cancel.light),
          audio: normalizeAudioBlock(step.on_cancel.audio),
        },
  };
}

function normalizeSnooze(snooze: SnoozeBlock | null | undefined): SnoozeBlock | null | undefined {
  return snooze == null
    ? snooze
    : {
        ...snooze,
        duration: toCompactDuration(snooze.duration),
        light: normalizeLightBlock(snooze.light),
        audio: normalizeAudioBlock(snooze.audio),
      };
}

/** See `utils/duration.ts::toCompactDuration`'s docstring: `GET
 * /api/routines/{id}` returns every `timedelta` field as an ISO-8601
 * duration, a grammar the same API's own `PUT` (and `routines/schema.json`)
 * rejects. Called once, right after fetching, so the rest of the UI (the
 * timeline layout, the simple form editor, a YAML export/re-import round
 * trip) only ever sees the compact form. */
export function normalizeRoutine(routine: Routine): Routine {
  return { ...routine, steps: routine.steps.map(normalizeStep), snooze: normalizeSnooze(routine.snooze) };
}
