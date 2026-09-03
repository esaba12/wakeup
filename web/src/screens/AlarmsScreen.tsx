import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { DayChips } from "../components/DayChips";
import { UndoToast } from "../components/UndoToast";
import type { Alarm, AlarmInput, RoutineSummary } from "../types";
import { formatClockTime, formatDays } from "../utils/format";

interface FormState {
  id?: string;
  enabled: boolean;
  time: string; // "HH:MM"
  days: number[];
  routine_id: string;
  pre_roll_min: number;
  timezone: string;
}

function alarmToForm(alarm: Alarm): FormState {
  return {
    id: alarm.id,
    enabled: alarm.enabled,
    time: alarm.time.slice(0, 5),
    days: alarm.days,
    routine_id: alarm.routine_id,
    pre_roll_min: Math.round(alarm.pre_roll_s / 60),
    timezone: alarm.timezone,
  };
}

function blankForm(defaultTz: string, defaultRoutine: string): FormState {
  return {
    enabled: true,
    time: "07:00",
    days: [1, 2, 3, 4, 5],
    routine_id: defaultRoutine,
    pre_roll_min: 20,
    timezone: defaultTz,
  };
}

export function AlarmsScreen({ tz }: { tz: string }): JSX.Element {
  const [alarms, setAlarms] = useState<Alarm[] | null>(null);
  const [routines, setRoutines] = useState<RoutineSummary[]>([]);
  const [editing, setEditing] = useState<FormState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Alarm | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    api.listAlarms().then(setAlarms).catch(() => setError("Could not load alarms"));
  };

  useEffect(() => {
    reload();
    api.listRoutines().then(setRoutines).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (form: FormState) => {
    const input: AlarmInput = {
      id: form.id,
      enabled: form.enabled,
      time: `${form.time}:00`,
      days: form.days,
      routine_id: form.routine_id,
      pre_roll_s: form.pre_roll_min * 60,
      timezone: form.timezone,
    };
    try {
      if (form.id) {
        await api.updateAlarm(form.id, input);
      } else {
        await api.createAlarm(input);
      }
      setEditing(null);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save alarm");
    }
  };

  const toggleEnabled = async (alarm: Alarm) => {
    setAlarms((prev) =>
      prev ? prev.map((a) => (a.id === alarm.id ? { ...a, enabled: !a.enabled } : a)) : prev
    );
    try {
      await api.updateAlarm(alarm.id, {
        enabled: !alarm.enabled,
        time: alarm.time,
        days: alarm.days,
        routine_id: alarm.routine_id,
        pre_roll_s: alarm.pre_roll_s,
        timezone: alarm.timezone,
      });
    } catch {
      reload(); // revert the optimistic flip on failure
    }
  };

  const skipNext = async (alarm: Alarm) => {
    try {
      const updated = await api.skipNextAlarm(alarm.id);
      setAlarms((prev) => (prev ? prev.map((a) => (a.id === alarm.id ? updated : a)) : prev));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not skip alarm");
    }
  };

  const requestDelete = (alarm: Alarm) => {
    setAlarms((prev) => (prev ? prev.filter((a) => a.id !== alarm.id) : prev));
    setPendingDelete(alarm);
  };

  const confirmDelete = async () => {
    if (pendingDelete === null) return;
    const alarm = pendingDelete;
    setPendingDelete(null);
    try {
      await api.deleteAlarm(alarm.id);
    } catch {
      reload();
    }
  };

  const undoDelete = () => {
    if (pendingDelete === null) return;
    setAlarms((prev) => (prev ? [...prev, pendingDelete] : prev));
    setPendingDelete(null);
  };

  return (
    <div className="screen">
      <h1 className="screen-title">Alarms</h1>
      {error && <p className="banner">{error}</p>}

      {alarms === null ? (
        <p className="muted">Loading…</p>
      ) : alarms.length === 0 ? (
        <div className="empty-state">No alarms yet. Add one below.</div>
      ) : (
        <div className="stack">
          {alarms
            .slice()
            .sort((a, b) => a.time.localeCompare(b.time))
            .map((alarm) => (
              <div key={alarm.id} className={`card${alarm.enabled ? "" : " alarm-disabled"}`}>
                <div className="alarm-row" style={{ padding: 0 }}>
                  <span className="alarm-time">{formatClockTime(alarm.time)}</span>
                  <div className="alarm-meta">
                    <div className="alarm-days">{formatDays(alarm.days)}</div>
                    <div className="faint">{alarm.routine_id}</div>
                  </div>
                  <button
                    type="button"
                    className={`toggle${alarm.enabled ? " toggle--on" : ""}`}
                    role="switch"
                    aria-checked={alarm.enabled}
                    aria-label={`${alarm.enabled ? "Disable" : "Enable"} alarm at ${alarm.time}`}
                    onClick={() => toggleEnabled(alarm)}
                  />
                </div>
                <div className="btn-row" style={{ marginTop: 10 }}>
                  <button
                    type="button"
                    className={`btn skip-toggle${alarm.skip_next ? " btn--primary" : ""}`}
                    style={{ flex: 1 }}
                    onClick={() => skipNext(alarm)}
                  >
                    {alarm.skip_next ? "Skipping next" : "Skip next"}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => setEditing(alarmToForm(alarm))}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => requestDelete(alarm)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
        </div>
      )}

      {editing === null ? (
        <button
          type="button"
          className="btn btn--primary btn--block btn--big"
          onClick={() => setEditing(blankForm(tz, routines[0]?.id ?? ""))}
        >
          Add alarm
        </button>
      ) : (
        <AlarmForm
          form={editing}
          routines={routines}
          onCancel={() => setEditing(null)}
          onSave={save}
        />
      )}

      {pendingDelete && (
        <UndoToast
          message={`Deleted alarm at ${formatClockTime(pendingDelete.time)}`}
          onUndo={undoDelete}
          onExpire={confirmDelete}
        />
      )}
    </div>
  );
}

function AlarmForm({
  form,
  routines,
  onCancel,
  onSave,
}: {
  form: FormState;
  routines: RoutineSummary[];
  onCancel: () => void;
  onSave: (form: FormState) => Promise<void>;
}): JSX.Element {
  const [local, setLocal] = useState(form);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    await onSave(local);
    setSaving(false);
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>{form.id ? "Edit alarm" : "New alarm"}</h2>
      <div className="field">
        <label htmlFor="alarm-time">Time</label>
        <input
          id="alarm-time"
          type="time"
          value={local.time}
          required
          onChange={(e) => setLocal({ ...local, time: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Repeat</label>
        <DayChips selected={local.days} onChange={(days) => setLocal({ ...local, days })} />
        <span className="faint">No days selected = one-time alarm.</span>
      </div>
      <div className="field">
        <label htmlFor="alarm-routine">Routine</label>
        <select
          id="alarm-routine"
          value={local.routine_id}
          required
          onChange={(e) => setLocal({ ...local, routine_id: e.target.value })}
        >
          {routines.length === 0 && <option value="">No routines available</option>}
          {routines.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="alarm-preroll">Pre-roll (minutes before the alarm the routine starts)</label>
        <input
          id="alarm-preroll"
          type="number"
          min={0}
          max={180}
          value={local.pre_roll_min}
          onChange={(e) => setLocal({ ...local, pre_roll_min: Number(e.target.value) })}
        />
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn--ghost" style={{ flex: 1 }} onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn btn--primary" style={{ flex: 1 }} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
