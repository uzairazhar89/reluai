"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";

/**
 * A shared clock for relative times ("3 minutes ago") in client components.
 *
 * During hydration it returns the server's render time, so server and client produce the same
 * text; afterwards it ticks every 15 seconds. Without this, relative times differ between the
 * server render and the browser and React reports a hydration mismatch.
 */
const TICK_MS = 15_000;
const NowContext = createContext<number | null>(null);

const subscribe = (onChange: () => void) => {
  const id = setInterval(onChange, TICK_MS);
  return () => clearInterval(id);
};
const clientNow = () => Math.floor(Date.now() / TICK_MS) * TICK_MS;

export function NowProvider({ serverNow, children }: { serverNow: string; children: ReactNode }) {
  const serverMs = Date.parse(serverNow);
  const now = useSyncExternalStore(subscribe, clientNow, () => serverMs);
  return <NowContext.Provider value={now}>{children}</NowContext.Provider>;
}

export function useNow(): Date {
  const now = useContext(NowContext);
  return new Date(now ?? clientNow());
}

const noopSubscribe = () => () => {};

/** False during server rendering and hydration, true once React runs in the browser. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}
