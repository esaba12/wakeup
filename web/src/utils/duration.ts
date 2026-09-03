/**
 * Mirrors `core/routines.py::parse_duration` exactly: a signed or unsigned
 * single-unit duration like `30m`, `90s`, `-3m`, `1h`. Used only to lay out
 * the static routine timeline (Routines screen) from a routine's own YAML
 * — never to compute a *live* ramp's position, which the server already
 * provides as `routine.progress` (docs/07: "clients never compute derived
 * state").
 */
const DURATION_RE = /^(-?)(\d+)(h|m|s)$/;
const UNIT_SECONDS: Record<string, number> = { s: 1, m: 60, h: 3600 };

export function parseDurationSeconds(value: string): number | null {
  const match = DURATION_RE.exec(value);
  if (match === null) return null;
  const [, sign, amount, unit] = match;
  const seconds = Number(amount) * UNIT_SECONDS[unit];
  return sign === "-" ? -seconds : seconds;
}

export function isValidDuration(value: string): boolean {
  return DURATION_RE.test(value);
}

/**
 * `GET`/`PUT /api/routines/{id}` round-trip `timedelta` fields (`duration`,
 * `at_offset`, `transition`, `over`, `fade_in`, `fade_out`, `sleep_timer`,
 * `escalate_after`, the snooze block's `duration`) through Pydantic's
 * default JSON mode, which serializes a `timedelta` as an ISO-8601 duration
 * (`"PT30M"`, `"-PT3M"`) — a completely different grammar from the compact
 * form (`"30m"`, `"-3m"`) that `routines/schema.json`'s `format: "duration"`
 * documents and `core/routines.py::parse_duration` is the only thing that
 * actually accepts on a PUT. That makes the REST API's own `GET` response
 * not round-trippable through its own `PUT` — a real docs/07/task-07 bug,
 * flagged in this task's report rather than fixed here (this task doesn't
 * own `core/routines.py` or `api/rest.py`). Every duration this UI reads
 * from the server is normalized back to the compact form immediately after
 * fetching (`api/client.ts::getRoutine`) so the rest of the app — and a
 * save-as-YAML round-trip — only ever has to deal with one grammar.
 */
const ISO_DURATION_RE = /^(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$/;

export function isoDurationToSeconds(value: string): number | null {
  const match = ISO_DURATION_RE.exec(value);
  if (match === null) return null;
  const [, sign, days, hours, minutes, seconds] = match;
  if (!days && !hours && !minutes && !seconds) return null; // "P" alone isn't a duration
  const total =
    Number(days ?? 0) * 86400 +
    Number(hours ?? 0) * 3600 +
    Number(minutes ?? 0) * 60 +
    Number(seconds ?? 0);
  return sign === "-" ? -total : total;
}

export function secondsToCompactDuration(totalSeconds: number): string {
  const sign = totalSeconds < 0 ? "-" : "";
  const abs = Math.abs(Math.round(totalSeconds));
  if (abs !== 0 && abs % 3600 === 0) return `${sign}${abs / 3600}h`;
  if (abs !== 0 && abs % 60 === 0) return `${sign}${abs / 60}m`;
  return `${sign}${abs}s`;
}

/** Accepts either grammar and always returns the compact form; anything
 * that's neither (`"until_cancel"`, `"until_next_step"`, `null`-ish
 * placeholders) passes through untouched. */
export function toCompactDuration(value: string): string {
  if (isValidDuration(value)) return value;
  const seconds = isoDurationToSeconds(value);
  return seconds === null ? value : secondsToCompactDuration(seconds);
}
