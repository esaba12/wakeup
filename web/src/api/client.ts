import type {
  Alarm,
  AlarmInput,
  AppState,
  AudioDevice,
  HealthPanel,
  HistoryEntry,
  LightDevice,
  Routine,
  RoutineSummary,
} from "../types";
import { resolveToken } from "./token";
import { normalizeRoutine } from "../yaml/routineYaml";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const token = resolveToken();

function idempotencyKey(): string {
  // Every button press gets its own key; a genuine retry (network flake,
  // double-tap) reuses the browser's own retry semantics — this exists so
  // this client obeys the server's documented convention (docs/07: "409 on
  // conflicting routine starts... idempotency keys on POSTs that fire
  // actions"), not to implement client-side retry itself.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request<T>(
  path: string,
  init: RequestInit & { idempotent?: boolean; rawBody?: boolean } = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!init.rawBody && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.idempotent) {
    headers.set("Idempotency-Key", idempotencyKey());
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  getState: () => request<AppState>("/api/state"),
  getHealth: () => request<HealthPanel>("/api/health"),

  listAlarms: () => request<Alarm[]>("/api/alarms"),
  createAlarm: (input: AlarmInput) =>
    request<Alarm>("/api/alarms", { method: "POST", body: json(input), idempotent: true }),
  updateAlarm: (id: string, input: AlarmInput) =>
    request<Alarm>(`/api/alarms/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: json(input),
    }),
  deleteAlarm: (id: string) =>
    request<void>(`/api/alarms/${encodeURIComponent(id)}`, { method: "DELETE" }),
  skipNextAlarm: (id: string) =>
    request<Alarm>(`/api/alarms/${encodeURIComponent(id)}/skip-next`, {
      method: "POST",
      idempotent: true,
    }),

  listRoutines: () => request<RoutineSummary[]>("/api/routines"),
  getRoutine: (id: string) =>
    request<Routine>(`/api/routines/${encodeURIComponent(id)}`).then(normalizeRoutine),
  putRoutineYaml: (id: string, yamlText: string) =>
    request<Routine>(`/api/routines/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: yamlText,
      rawBody: true,
      headers: { "Content-Type": "application/x-yaml" },
    }).then(normalizeRoutine),
  startRoutine: (id: string, triggerAt?: string) =>
    request(`/api/routines/${encodeURIComponent(id)}/start`, {
      method: "POST",
      body: json({ trigger_at: triggerAt ?? null }),
      idempotent: true,
    }),
  stopRoutine: () =>
    request("/api/routines/current/stop", { method: "POST", idempotent: true }),

  snooze: () => request("/api/snooze", { method: "POST", idempotent: true }),
  dismiss: () => request("/api/dismiss", { method: "POST", idempotent: true }),

  lightPreset: (preset: "nightlight" | "reading" | "off") =>
    request(`/api/light/preset/${preset}`, { method: "POST", idempotent: true }),
  lightState: (brightness: number | null, cct: number | null) =>
    request("/api/light/state", {
      method: "POST",
      body: json({ brightness, cct }),
      idempotent: true,
    }),

  audioPlay: (source: string, gainDb: number | null, sleepTimer: number | null) =>
    request("/api/audio/play", {
      method: "POST",
      body: json({ source, gain_db: gainDb, sleep_timer: sleepTimer }),
      idempotent: true,
    }),
  audioStop: () => request("/api/audio/stop", { method: "POST", idempotent: true }),

  listLightDevices: () =>
    request<{ configured: LightDevice[]; discovered: LightDevice[] }>("/api/devices/lights"),
  discoverLights: () =>
    request("/api/devices/lights/discover", { method: "POST", idempotent: true }),
  listAudioDevices: () => request<AudioDevice[]>("/api/devices/audio"),
  testAudioDevice: () => request("/api/devices/audio/test", { method: "POST", idempotent: true }),

  getHistory: (days = 7) => request<HistoryEntry[]>(`/api/history?days=${days}`),
};

export function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${proto}//${window.location.host}/api/events`);
  if (token) url.searchParams.set("token", token);
  return url.toString();
}
