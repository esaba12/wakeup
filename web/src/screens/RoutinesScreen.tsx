import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { RoutineTimeline } from "../components/RoutineTimeline";
import type { Routine, RoutineStep, RoutineSummary } from "../types";
import { isValidDuration } from "../utils/duration";
import { dumpRoutine, validateRoutineYamlText } from "../yaml/routineYaml";
import type { ValidationError } from "../yaml/schema";

type Mode = "timeline" | "form" | "yaml";

export function RoutinesScreen(): JSX.Element {
  const [routines, setRoutines] = useState<RoutineSummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [routine, setRoutine] = useState<Routine | null>(null);
  const [mode, setMode] = useState<Mode>("timeline");
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const reloadList = () => {
    api.listRoutines().then(setRoutines).catch(() => setError("Could not load routines"));
  };

  useEffect(reloadList, []);

  useEffect(() => {
    if (selectedId === null) {
      setRoutine(null);
      return;
    }
    api
      .getRoutine(selectedId)
      .then(setRoutine)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load routine"));
  }, [selectedId]);

  const startRoutine = async (id: string) => {
    try {
      await api.startRoutine(id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start routine");
    }
  };

  const exportRoutine = () => {
    if (routine === null) return;
    const text = dumpRoutine(routine);
    const blob = new Blob([text], { type: "application/x-yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${routine.id}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const importFile = async (file: File) => {
    const text = await file.text();
    setMode("yaml");
    setPendingYaml(text);
  };

  const [pendingYaml, setPendingYaml] = useState<string | null>(null);

  if (routines === null) {
    return (
      <div className="screen">
        <h1 className="screen-title">Routines</h1>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (routine !== null && selectedId !== null) {
    return (
      <div className="screen">
        <button type="button" className="btn btn--ghost" onClick={() => setSelectedId(null)}>
          ← All routines
        </button>
        {error && <p className="banner">{error}</p>}
        <h1 className="screen-title">{routine.name}</h1>
        <div className="btn-row">
          <button
            type="button"
            className={`btn${mode === "timeline" ? " btn--primary" : ""}`}
            onClick={() => setMode("timeline")}
          >
            Timeline
          </button>
          <button
            type="button"
            className={`btn${mode === "form" ? " btn--primary" : ""}`}
            onClick={() => setMode("form")}
          >
            Form
          </button>
          <button
            type="button"
            className={`btn${mode === "yaml" ? " btn--primary" : ""}`}
            onClick={() => setMode("yaml")}
          >
            YAML
          </button>
        </div>

        {mode === "timeline" && (
          <div className="stack">
            <RoutineTimeline routine={routine} />
            <button type="button" className="btn btn--primary" onClick={() => startRoutine(routine.id)}>
              Start now
            </button>
          </div>
        )}

        {mode === "form" && (
          <RoutineFormEditor
            routine={routine}
            onSaved={(saved) => {
              setRoutine(saved);
              reloadList();
            }}
            onError={setError}
          />
        )}

        {mode === "yaml" && (
          <RoutineYamlEditor
            routineId={routine.id}
            initialText={pendingYaml ?? dumpRoutine(routine)}
            onSaved={(saved) => {
              setRoutine(saved);
              setPendingYaml(null);
              reloadList();
            }}
          />
        )}

        <div className="card row">
          <span className="muted">Export / import</span>
          <div className="btn-row">
            <button type="button" className="btn" onClick={exportRoutine}>
              Export
            </button>
            <button type="button" className="btn" onClick={() => fileInput.current?.click()}>
              Import
            </button>
          </div>
        </div>
        <input
          ref={fileInput}
          type="file"
          accept=".yaml,.yml,.json,application/x-yaml,application/json,text/yaml"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importFile(file);
            e.target.value = "";
          }}
        />
      </div>
    );
  }

  return (
    <div className="screen">
      <h1 className="screen-title">Routines</h1>
      {error && <p className="banner">{error}</p>}
      {routines.length === 0 ? (
        <div className="empty-state">No routines found in the routines directory.</div>
      ) : (
        <div className="stack">
          {routines.map((r) => (
            <button
              key={r.id}
              type="button"
              className="card row"
              style={{ textAlign: "left", width: "100%", border: "1px solid var(--border)" }}
              onClick={() => setSelectedId(r.id)}
            >
              <span>
                <strong>{r.name}</strong>
                <div className="faint">{r.trigger.type === "alarm" ? "Bound to an alarm" : `Daily at ${r.trigger.at ?? "?"}`}</div>
              </span>
              <span className="muted">→</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RoutineFormEditor({
  routine,
  onSaved,
  onError,
}: {
  routine: Routine;
  onSaved: (routine: Routine) => void;
  onError: (message: string) => void;
}): JSX.Element {
  const [name, setName] = useState(routine.name);
  const [steps, setSteps] = useState<RoutineStep[]>(routine.steps);
  const [saving, setSaving] = useState(false);

  const updateStep = (index: number, patch: Partial<RoutineStep>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const save = async () => {
    for (const step of steps) {
      if (
        typeof step.duration === "string" &&
        step.duration !== "until_cancel" &&
        step.duration !== "until_next_step" &&
        !isValidDuration(step.duration)
      ) {
        onError(`Step ${step.id}: invalid duration ${JSON.stringify(step.duration)}`);
        return;
      }
    }
    setSaving(true);
    try {
      const updated: Routine = { ...routine, name, steps };
      const saved = await api.putRoutineYaml(routine.id, dumpRoutine(updated));
      onSaved(saved);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Could not save routine");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card stack">
      <div className="field">
        <label htmlFor="routine-name">Name</label>
        <input id="routine-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <span className="muted">Steps (simple fields only — switch to YAML for on_cancel, escalation, or offset triggers)</span>
      {steps.map((step, i) => (
        <div key={step.id} className="card stack">
          <span className="faint">{step.id}</span>
          <div className="field">
            <label htmlFor={`step-${i}-duration`}>Duration</label>
            <input
              id={`step-${i}-duration`}
              type="text"
              placeholder="e.g. 30m, until_cancel"
              value={typeof step.duration === "string" ? step.duration : ""}
              disabled={step.at_offset != null}
              onChange={(e) => updateStep(i, { duration: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor={`step-${i}-brightness`}>Light brightness (0-1, blank = unchanged)</label>
            <input
              id={`step-${i}-brightness`}
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={step.light?.brightness ?? ""}
              onChange={(e) =>
                updateStep(i, {
                  light: { ...step.light, brightness: e.target.value === "" ? null : Number(e.target.value) },
                })
              }
            />
          </div>
          <div className="field">
            <label htmlFor={`step-${i}-audio`}>Audio source (blank = none)</label>
            <input
              id={`step-${i}-audio`}
              type="text"
              placeholder="file:rain.flac"
              value={step.audio?.source ?? ""}
              onChange={(e) =>
                updateStep(i, { audio: { ...step.audio, source: e.target.value || null } })
              }
            />
          </div>
        </div>
      ))}
      <button type="button" className="btn btn--primary" disabled={saving} onClick={save}>
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

function RoutineYamlEditor({
  routineId,
  initialText,
  onSaved,
}: {
  routineId: string;
  initialText: string;
  onSaved: (routine: Routine) => void;
}): JSX.Element {
  const [text, setText] = useState(initialText);
  const [errors, setErrors] = useState<ValidationError[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const validate = async () => {
    const result = await validateRoutineYamlText(text);
    setErrors(result.errors);
    return result.errors.length === 0;
  };

  const save = async () => {
    setSaveError(null);
    const ok = await validate();
    if (!ok) return;
    setSaving(true);
    try {
      const saved = await api.putRoutineYaml(routineId, text);
      onSaved(saved);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Could not save routine");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card stack">
      <div className="field">
        <label htmlFor="routine-yaml">Routine YAML</label>
        <textarea
          id="routine-yaml"
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {errors !== null && errors.length > 0 && (
        <ul className="errors-list">
          {errors.map((e, i) => (
            <li key={i}>
              {e.path}: {e.message}
            </li>
          ))}
        </ul>
      )}
      {saveError && <p className="banner">{saveError}</p>}
      <div className="btn-row">
        <button type="button" className="btn" onClick={validate}>
          Validate
        </button>
        <button type="button" className="btn btn--primary" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
