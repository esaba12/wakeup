import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { AudioDevice, HealthPanel, HistoryEntry, LightDevice } from "../types";
import { formatDateTime } from "../utils/format";

export function SettingsScreen({ tz }: { tz: string }): JSX.Element {
  const [health, setHealth] = useState<HealthPanel | null>(null);
  const [lights, setLights] = useState<{ configured: LightDevice[]; discovered: LightDevice[] } | null>(
    null
  );
  const [audioDevices, setAudioDevices] = useState<AudioDevice[] | null>(null);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    api.getHealth().then(setHealth).catch(() => undefined);
    api.listLightDevices().then(setLights).catch(() => undefined);
    api.listAudioDevices().then(setAudioDevices).catch(() => undefined);
    api.getHistory(7).then(setHistory).catch(() => undefined);
  };

  useEffect(reload, []);

  const testAudio = async () => {
    setTestStatus("Playing test tone…");
    try {
      await api.testAudioDevice();
      setTestStatus("Test tone sent");
    } catch (err) {
      setTestStatus(null);
      setError(err instanceof ApiError ? err.message : "Audio test failed");
    }
  };

  const discover = async () => {
    try {
      await api.discoverLights();
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Discovery failed");
    }
  };

  return (
    <div className="screen">
      <h1 className="screen-title">Settings</h1>
      {error && <p className="banner">{error}</p>}

      <section className="card stack">
        <h2>Devices</h2>
        <div className="row">
          <span className="muted">Light</span>
          <span>
            {lights?.configured[0]
              ? `${lights.configured[0].id} · ${lights.configured[0].reachable ? "reachable" : "unreachable"}`
              : "—"}
          </span>
        </div>
        <button type="button" className="btn" onClick={discover}>
          Discover lights
        </button>
        {lights !== null && lights.discovered.length > 0 && (
          <ul>
            {lights.discovered.map((d) => (
              <li key={d.id} className="muted">
                {d.id}
              </li>
            ))}
          </ul>
        )}
        <div className="row">
          <span className="muted">Audio output</span>
          <span>{audioDevices?.[0]?.id ?? "—"}</span>
        </div>
        <button type="button" className="btn" onClick={testAudio}>
          Play test tone
        </button>
        {testStatus && <span className="faint">{testStatus}</span>}
      </section>

      <section className="card stack">
        <h2>Clock &amp; volume</h2>
        <div className="row">
          <span className="muted">Timezone</span>
          <span>{tz}</span>
        </div>
        <p className="faint">
          Timezone and max-volume ceiling are set in the daemon's config, not the web UI yet — no
          REST endpoint exists to change them (docs/07-api-and-state.md's endpoint list has no
          config-write route; flagged in the task report).
        </p>
      </section>

      <section className="card stack">
        <h2>Health</h2>
        {health === null ? (
          <p className="muted">Loading…</p>
        ) : (
          <div className="health-grid">
            <span className="health-item">
              <span className={`dot ${health.status === "ok" ? "dot--ok" : "dot--bad"}`} />
              {health.status}
            </span>
            <span className="health-item">
              <span className={`dot ${health.clock_synced ? "dot--ok" : "dot--bad"}`} />
              clock {health.clock_synced ? "synced" : "unsynced"}
            </span>
            <span className="health-item">
              <span className={`dot ${health.light_reachable ? "dot--ok" : "dot--bad"}`} />
              light {health.light_reachable ? "reachable" : "unreachable"}
            </span>
            <span className="health-item">
              <span className={`dot ${health.audio_available ? "dot--ok" : "dot--bad"}`} />
              audio {health.audio_available ? "available" : "unavailable"}
            </span>
          </div>
        )}
      </section>

      <section className="card stack">
        <h2>Alarm history (7 days)</h2>
        {history === null ? (
          <p className="muted">Loading…</p>
        ) : history.length === 0 ? (
          <p className="muted">No occurrences yet.</p>
        ) : (
          <div>
            {history.map((h, i) => (
              <div key={i} className="history-row">
                <span>{h.alarm_id}</span>
                <span className="muted">{h.fired_at ? formatDateTime(h.fired_at) : h.local_date}</span>
                <span className={h.outcome === "fired" ? "" : "muted"}>{h.outcome}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
