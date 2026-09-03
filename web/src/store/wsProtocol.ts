import type { AppState } from "../types";

/**
 * Server -> client frames (`api/ws.py`): `state` on connect (the full
 * object), `delta` after that (a shallow top-level diff -
 * `core/state.py::state_delta`), and `ack`/`error` replies to a
 * client -> server action message. This UI drives writes over REST (see
 * `api/client.ts`), not the WS action protocol, so `ack`/`error` frames are
 * only handled defensively here.
 */
export type ServerMessage =
  | { type: "state"; data: AppState }
  | { type: "delta"; data: Partial<AppState> }
  | { type: "ack"; action: string; data: unknown }
  | { type: "error"; action?: string; error: string };

/**
 * Pure reducer: fold one server frame into the current state. `null` means
 * "no state yet" (before the first `state` frame ever arrives, e.g. right
 * after a fresh page load). A `delta` before any `state` frame is dropped
 * rather than guessed at — the very next reconnect attempt will get a full
 * `state` frame to resync from (docs/07 acceptance: "reconnects and
 * resyncs without a full page reload").
 */
export function applyServerMessage(
  current: AppState | null,
  message: ServerMessage
): AppState | null {
  switch (message.type) {
    case "state":
      return message.data;
    case "delta":
      return current === null ? null : { ...current, ...message.data };
    default:
      return current;
  }
}

export function parseServerMessage(raw: string): ServerMessage | null {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.type === "string") {
      return parsed as ServerMessage;
    }
  } catch {
    // malformed frame; caller ignores it
  }
  return null;
}
