/** Rendering helpers only — every number here comes from the server
 * already computed (docs/07: "clients never compute derived state; they
 * render what they're given"). No wall-clock math lives in this file. */

export function formatDurationShort(totalSeconds: number): string {
  const sign = totalSeconds < 0 ? "-" : "";
  const s = Math.abs(Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${sign}${h}h ${m}m`;
  const secs = s % 60;
  if (m > 0) return `${sign}${m}m ${secs}s`;
  return `${sign}${secs}s`;
}

export function formatClockTime(isoOrHms: string, timeZone?: string): string {
  // Accepts either a full ISO datetime or a bare "HH:MM:SS" wall time.
  const bare = /^\d{2}:\d{2}(:\d{2})?$/.exec(isoOrHms);
  if (bare) {
    const [h, m] = isoOrHms.split(":").map(Number);
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const d = new Date(isoOrHms);
  if (Number.isNaN(d.getTime())) return isoOrHms;
  return d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

const DAY_NAMES: Record<number, string> = {
  1: "Mon",
  2: "Tue",
  3: "Wed",
  4: "Thu",
  5: "Fri",
  6: "Sat",
  7: "Sun",
};

export function dayName(iso: number): string {
  return DAY_NAMES[iso] ?? "?";
}

export function formatDays(days: number[]): string {
  if (days.length === 0) return "One-time";
  if (days.length === 7) return "Every day";
  const weekdays = [1, 2, 3, 4, 5];
  const weekend = [6, 7];
  if (days.length === 5 && weekdays.every((d) => days.includes(d))) return "Weekdays";
  if (days.length === 2 && weekend.every((d) => days.includes(d))) return "Weekends";
  return [...days].sort((a, b) => a - b).map(dayName).join(", ");
}
