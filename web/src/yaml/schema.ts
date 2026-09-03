import { isValidDuration } from "../utils/duration";

/**
 * A deliberately small JSON Schema validator — just the subset that
 * `routines/schema.json` (task 05) actually uses: `$ref`/`$defs`,
 * `type`, `const`, `enum`, `anyOf`, `properties` + `required` +
 * `additionalProperties: false`, `items`, and the schema's one custom
 * `format: "duration"` (checked against the same `h|m|s` grammar
 * `core/routines.py::parse_duration` accepts).
 *
 * A general-purpose validator (ajv) would cover more of the JSON Schema
 * spec than this file ever needs, at real bundle-size cost for a Pi-served
 * app; this hand-rolled one is scoped to exactly the schema it validates
 * and is trivial to re-check by eye against `routines/schema.json`.
 */

export interface JsonSchema {
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  type?: string;
  const?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean;
  items?: JsonSchema;
  format?: string;
  title?: string;
}

export interface ValidationError {
  path: string;
  message: string;
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value; // "string" | "number" | "boolean" | "object" | "undefined"
}

function checkType(schema: JsonSchema, value: unknown): boolean {
  if (schema.type === undefined) return true;
  const actual = typeOf(value);
  if (schema.type === "number") return actual === "number";
  if (schema.type === "integer") return actual === "number" && Number.isInteger(value);
  return actual === schema.type;
}

class Validator {
  constructor(private readonly root: JsonSchema) {}

  private resolve(schema: JsonSchema): JsonSchema {
    if (schema.$ref === undefined) return schema;
    const match = /^#\/\$defs\/(.+)$/.exec(schema.$ref);
    if (match === null || this.root.$defs === undefined) {
      throw new Error(`unsupported $ref ${schema.$ref}`);
    }
    const target = this.root.$defs[match[1]];
    if (target === undefined) throw new Error(`unknown $ref target ${schema.$ref}`);
    return target;
  }

  validate(schema: JsonSchema, value: unknown, path: string, errors: ValidationError[]): void {
    const resolved = this.resolve(schema);

    if (resolved.anyOf !== undefined) {
      const matches = resolved.anyOf.some((branch) => {
        const branchErrors: ValidationError[] = [];
        this.validate(branch, value, path, branchErrors);
        return branchErrors.length === 0;
      });
      if (!matches) {
        errors.push({ path, message: "does not match any allowed form" });
      }
      return;
    }

    if (resolved.const !== undefined && value !== resolved.const) {
      errors.push({ path, message: `must equal ${JSON.stringify(resolved.const)}` });
      return;
    }

    if (resolved.enum !== undefined && !resolved.enum.includes(value)) {
      errors.push({ path, message: `must be one of ${JSON.stringify(resolved.enum)}` });
      return;
    }

    if (!checkType(resolved, value)) {
      errors.push({ path, message: `expected ${resolved.type ?? "value"}, got ${typeOf(value)}` });
      return;
    }

    if (resolved.format === "duration" && typeof value === "string" && !isValidDuration(value)) {
      errors.push({ path, message: "invalid duration; expected e.g. '30m', '90s', '-3m'" });
      return;
    }

    if (resolved.type === "object" && typeof value === "object" && value !== null) {
      const obj = value as Record<string, unknown>;
      for (const key of resolved.required ?? []) {
        if (!(key in obj)) {
          errors.push({ path: `${path}.${key}`, message: "required field missing" });
        }
      }
      if (resolved.additionalProperties === false && resolved.properties !== undefined) {
        for (const key of Object.keys(obj)) {
          if (!(key in resolved.properties)) {
            errors.push({ path: `${path}.${key}`, message: "unknown field" });
          }
        }
      }
      for (const [key, propSchema] of Object.entries(resolved.properties ?? {})) {
        if (key in obj) {
          this.validate(propSchema, obj[key], `${path}.${key}`, errors);
        }
      }
    }

    if (resolved.type === "array" && Array.isArray(value) && resolved.items !== undefined) {
      value.forEach((item, index) => {
        this.validate(resolved.items as JsonSchema, item, `${path}[${index}]`, errors);
      });
    }
  }
}

export function validateRoutine(schema: JsonSchema, data: unknown): ValidationError[] {
  const errors: ValidationError[] = [];
  try {
    new Validator(schema).validate(schema, data, "$", errors);
  } catch (err) {
    errors.push({ path: "$", message: err instanceof Error ? err.message : String(err) });
  }
  return errors;
}
