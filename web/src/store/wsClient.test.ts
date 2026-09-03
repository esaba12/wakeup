import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppState } from "../types";
import { EventsClient, type WebSocketLike } from "./wsClient";

class FakeSocket implements WebSocketLike {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  closed = false;

  constructor(public readonly url: string) {
    FakeSocket.instances.push(this);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }

  static instances: FakeSocket[] = [];
  static reset(): void {
    FakeSocket.instances = [];
  }
}

function sampleState(health: string): AppState {
  return {
    clock: { now: "2026-09-03T22:00:00-04:00", tz: "UTC", synced: true, source: "ntp" },
    routine: { id: null, state: "IDLE", step: null, started_at: null, trigger_at: null, progress: null },
    light: { id: "mock", reachable: true, on: false, brightness: 0, cct: null },
    audio: { output: "mock", available: true, playing: null, gain_db: -60 },
    next_alarm: null,
    health,
  };
}

describe("EventsClient", () => {
  beforeEach(() => {
    FakeSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("notifies subscribers on connect and on each state/delta frame", () => {
    const client = new EventsClient("ws://test/api/events", (url) => new FakeSocket(url));
    const seen: { connected: boolean; health: string | null }[] = [];
    client.subscribe((state, connected) => seen.push({ connected, health: state?.health ?? null }));

    client.connect();
    const sock = FakeSocket.instances[0];
    sock.onopen?.();
    expect(seen.at(-1)).toEqual({ connected: true, health: null });

    sock.onmessage?.({ data: JSON.stringify({ type: "state", data: sampleState("ok") }) });
    expect(seen.at(-1)).toEqual({ connected: true, health: "ok" });

    sock.onmessage?.({ data: JSON.stringify({ type: "delta", data: { health: "degraded" } }) });
    expect(seen.at(-1)).toEqual({ connected: true, health: "degraded" });
  });

  it("marks disconnected on close and reconnects with backoff, resyncing on the new connection", () => {
    const client = new EventsClient("ws://test/api/events", (url) => new FakeSocket(url));
    const connections: boolean[] = [];
    client.subscribe((_state, connected) => connections.push(connected));

    client.connect();
    FakeSocket.instances[0].onopen?.();
    FakeSocket.instances[0].onmessage?.({
      data: JSON.stringify({ type: "state", data: sampleState("ok") }),
    });

    // Server drops the connection unexpectedly.
    FakeSocket.instances[0].onclose?.();
    expect(connections.at(-1)).toBe(false);
    expect(FakeSocket.instances).toHaveLength(1); // no reconnect attempted yet

    vi.advanceTimersByTime(1000); // first backoff step
    expect(FakeSocket.instances).toHaveLength(2);

    // The new connection resyncs with a fresh full state, not a stale delta.
    const seenStates: (AppState | null)[] = [];
    client.subscribe((state) => {
      seenStates.push(state);
    });
    FakeSocket.instances[1].onopen?.();
    FakeSocket.instances[1].onmessage?.({
      data: JSON.stringify({ type: "state", data: sampleState("degraded") }),
    });
    expect(seenStates.at(-1)?.health).toBe("degraded");
  });

  it("does not reconnect after an explicit close()", () => {
    const client = new EventsClient("ws://test/api/events", (url) => new FakeSocket(url));
    client.connect();
    client.close();
    expect(FakeSocket.instances[0].closed).toBe(true);

    vi.advanceTimersByTime(30_000);
    expect(FakeSocket.instances).toHaveLength(1); // never reconnected
  });

  it("keeps the last known state visible while disconnected (no blanking)", () => {
    const client = new EventsClient("ws://test/api/events", (url) => new FakeSocket(url));
    const seen: { state: AppState | null; connected: boolean }[] = [];
    client.subscribe((state, connected) => {
      seen.push({ state, connected });
    });

    client.connect();
    FakeSocket.instances[0].onmessage?.({
      data: JSON.stringify({ type: "state", data: sampleState("ok") }),
    });
    FakeSocket.instances[0].onclose?.();

    expect(seen.at(-1)?.connected).toBe(false);
    expect(seen.at(-1)?.state?.health).toBe("ok"); // stale-but-visible, not cleared
  });
});
