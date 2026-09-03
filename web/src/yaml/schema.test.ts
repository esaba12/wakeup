import { readFileSync } from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { describe, expect, it } from "vitest";
import schema from "../../public/routine-schema.json";
import { validateRoutine } from "./schema";
import type { JsonSchema } from "./schema";

// vitest's `cwd` is `web/` (this project's own dir); the shipped routine
// YAML lives one level up, at the repo root's `routines/`.
const repoRoot = path.resolve(process.cwd(), "..");

function loadRoutineYaml(name: string): unknown {
  const text = readFileSync(path.join(repoRoot, "routines", name), "utf-8");
  return yaml.load(text);
}

describe("validateRoutine against the real routines/schema.json", () => {
  it("accepts the shipped weekday-wake.yaml routine", () => {
    const data = loadRoutineYaml("weekday-wake.yaml");
    expect(validateRoutine(schema as JsonSchema, data)).toEqual([]);
  });

  it("accepts the shipped winddown.yaml routine", () => {
    const data = loadRoutineYaml("winddown.yaml");
    expect(validateRoutine(schema as JsonSchema, data)).toEqual([]);
  });

  it("rejects a routine missing a required top-level field", () => {
    const data = loadRoutineYaml("weekday-wake.yaml") as Record<string, unknown>;
    delete data.trigger;
    const errors = validateRoutine(schema as JsonSchema, data);
    expect(errors).toContainEqual({ path: "$.trigger", message: "required field missing" });
  });

  it("rejects an unknown top-level field (additionalProperties: false)", () => {
    const data = loadRoutineYaml("weekday-wake.yaml") as Record<string, unknown>;
    data.bogus_field = true;
    const errors = validateRoutine(schema as JsonSchema, data);
    expect(errors).toContainEqual({ path: "$.bogus_field", message: "unknown field" });
  });

  it("rejects a malformed duration string inside a nested block", () => {
    const data = loadRoutineYaml("weekday-wake.yaml") as any;
    data.steps[0].duration = "30 minutes";
    const errors = validateRoutine(schema as JsonSchema, data);
    expect(errors.some((e) => e.path === "$.steps[0].duration")).toBe(true);
  });

  it("rejects a wrong-type version (const 1, not '1')", () => {
    const data = loadRoutineYaml("weekday-wake.yaml") as Record<string, unknown>;
    data.version = "1";
    const errors = validateRoutine(schema as JsonSchema, data);
    expect(errors.some((e) => e.path === "$.version")).toBe(true);
  });
});
