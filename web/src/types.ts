/**
 * Mirrors the JSON shapes in docs/07-api-and-state.md and
 * `src/openrestore/core/state.py::state_to_dict` / `api/actions.py`.
 * The daemon is the single source of truth (docs/07: "clients never
 * compute derived state; they render what they're given") — these types
 * exist to keep the UI honest about what the server actually sends, not
 * to add client-side derivation.
 */

export type RoutineStateName =
  | "IDLE"
  | "WINDDOWN"
  | "ASLEEP"
  | "SUNRISE"
  | "ALARM"
  | "SNOOZE"
  | "AWAKE";

export interface ClockView {
  now: string; // ISO-8601 with offset
  tz: string;
  synced: boolean;
  source: string | null;
}

export interface RoutineView {
  id: string | null;
  state: RoutineStateName;
  step: string | null;
  started_at: string | null;
  trigger_at: string | null;
  progress: number | null;
}

export interface LightView {
  id: string;
  reachable: boolean;
  on: boolean;
  brightness: number;
  cct: number | null;
}

export interface AudioView {
  output: string;
  available: boolean;
  playing: string | null;
  gain_db: number;
}

export interface NextAlarmView {
  id: string;
  at: string;
  in_s: number;
  skipped: boolean;
}

export interface AppState {
  clock: ClockView;
  routine: RoutineView;
  light: LightView;
  audio: AudioView;
  next_alarm: NextAlarmView | null;
  health: string;
}

/** `api/actions.py::alarm_to_dict`. */
export interface Alarm {
  id: string;
  enabled: boolean;
  time: string; // "HH:MM:SS" local wall time
  days: number[]; // ISO weekdays 1-7; [] = one-shot
  routine_id: string;
  pre_roll_s: number;
  timezone: string;
  skip_next: boolean;
  last_fired_at: string | null;
}

export interface AlarmInput {
  id?: string;
  enabled: boolean;
  time: string;
  days: number[];
  routine_id: string;
  pre_roll_s: number;
  timezone: string;
}

/** `GET /api/routines` list entry. */
export interface RoutineSummary {
  id: string;
  name: string;
  trigger: RoutineTrigger;
}

export interface RoutineTrigger {
  type: "alarm" | "time";
  ref?: string | null;
  at?: string | null;
  days?: number[] | null;
}

export interface LightTarget {
  brightness?: number | null;
  cct?: number | null;
}

export interface LightBlock {
  curve?: string | null;
  to?: LightTarget | null;
  brightness?: number | null;
  cct?: number | null;
  transition?: string | null;
  off?: boolean | null;
  hold?: boolean | null;
  reverse?: boolean;
}

export interface AudioBlock {
  source?: string | null;
  gain_db?: number | null;
  ramp_to_db?: number | null;
  over?: string | null;
  fade_in?: string | null;
  fade_out?: string | null;
  continue?: boolean | null;
  sleep_timer?: string | null;
  stop?: boolean | null;
}

export interface OnCancel {
  light?: LightBlock | null;
  audio?: AudioBlock | null;
}

export interface RoutineStep {
  id: string;
  duration?: string | "until_cancel" | "until_next_step" | null;
  at_offset?: string | null;
  ends_at?: "trigger" | null;
  light?: LightBlock | null;
  audio?: AudioBlock | null;
  on_cancel?: OnCancel | null;
  escalate_after?: string | null;
}

export interface SnoozeBlock {
  duration: string;
  max: number;
  light?: LightBlock | null;
  audio?: AudioBlock | null;
}

/** Full `GET/PUT /api/routines/{id}` document — `routines/schema.json`. */
export interface Routine {
  version: 1;
  name: string;
  id: string;
  trigger: RoutineTrigger;
  steps: RoutineStep[];
  snooze?: SnoozeBlock | null;
}

export interface HealthPanel {
  status: string;
  clock_synced: boolean;
  light_reachable: boolean;
  audio_available: boolean;
}

export interface HistoryEntry {
  alarm_id: string;
  local_date: string;
  fired_at: string | null;
  outcome: string;
}

export interface LightDevice {
  id: string;
  reachable: boolean;
}

export interface AudioDevice {
  id: string;
  description: string;
}
