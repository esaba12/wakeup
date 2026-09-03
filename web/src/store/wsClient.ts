import type { AppState } from "../types";
import { applyServerMessage, parseServerMessage } from "./wsProtocol";

export type ConnectionListener = (state: AppState | null, connected: boolean) => void;

const MAX_BACKOFF_MS = 15_000;
const BASE_BACKOFF_MS = 1_000;

/** Minimal shape of the WebSocket API this client needs — lets tests
 * inject a fake instead of relying on jsdom's real (network-backed) one. */
export interface WebSocketLike {
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  close(): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

const defaultFactory: WebSocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

/**
 * Owns the single `/api/events` connection (docs/08-web-ui.md: "One
 * WebSocket connection into a small store"). Reconnects with capped
 * exponential backoff on any drop and relies on the server always sending
 * a full `state` frame on a fresh connect to resync — no manual "catch up"
 * logic needed here. `connected` drives the disconnected banner; the last
 * known state is kept (not cleared) so the UI can dim it instead of
 * flashing to blank.
 */
export class EventsClient {
  private ws: WebSocketLike | null = null;
  private state: AppState | null = null;
  private connected = false;
  private listeners = new Set<ConnectionListener>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = true;

  constructor(
    private readonly url: string,
    private readonly factory: WebSocketFactory = defaultFactory
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
  }

  subscribe(listener: ConnectionListener): () => void {
    this.listeners.add(listener);
    listener(this.state, this.connected);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private open(): void {
    const ws = this.factory(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.connected = true;
      this.emit();
    };
    ws.onmessage = (ev) => {
      const message = parseServerMessage(ev.data);
      if (message === null) return;
      this.state = applyServerMessage(this.state, message);
      this.emit();
    };
    ws.onerror = () => {
      ws.close();
    };
    ws.onclose = () => {
      this.connected = false;
      this.ws = null;
      this.emit();
      if (!this.closedByUser) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = Math.min(BASE_BACKOFF_MS * 2 ** this.reconnectAttempt, MAX_BACKOFF_MS);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      if (!this.closedByUser) this.open();
    }, delay);
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.state, this.connected);
  }
}
