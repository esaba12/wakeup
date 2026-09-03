import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { wsUrl } from "../api/client";
import type { AppState } from "../types";
import { EventsClient } from "./wsClient";

interface StoreValue {
  state: AppState | null;
  connected: boolean;
}

const StoreContext = createContext<StoreValue>({ state: null, connected: false });

export function AppStoreProvider({ children }: { children: ReactNode }): JSX.Element {
  const clientRef = useRef<EventsClient | null>(null);
  const [value, setValue] = useState<StoreValue>({ state: null, connected: false });

  useEffect(() => {
    const client = new EventsClient(wsUrl());
    clientRef.current = client;
    const unsubscribe = client.subscribe((state, connected) => setValue({ state, connected }));
    client.connect();
    return () => {
      unsubscribe();
      client.close();
    };
  }, []);

  const memoized = useMemo(() => value, [value]);
  return <StoreContext.Provider value={memoized}>{children}</StoreContext.Provider>;
}

/** The live daemon state (or `null` before the first WS frame) plus
 * whether the socket is currently connected. Screens render what they're
 * given (docs/07) — no client-side derivation of `progress`/`in_s`. */
export function useAppState(): StoreValue {
  return useContext(StoreContext);
}
