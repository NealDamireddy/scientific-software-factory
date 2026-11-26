"use client";

import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { createLiveClient } from "../lib/live/client.ts";
import { parseRoute, routeHref } from "../lib/route.ts";
import type { Route } from "../lib/route.ts";
import { createSampleClient } from "../lib/sample/client.ts";
import type { LabFactoryClient, Role } from "../lib/types.ts";

export type Theme = "system" | "light" | "dark";
export type ClientMode = "sample" | "live";
/** The sample client also has reset(); the live client does not. */
export type AppClient = LabFactoryClient & { reset?: () => Promise<void> };

export type ClientValue = {
  client: AppClient;
  mode: ClientMode;
  labId: string;
  role: Role;
  setRole: (role: Role) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** Bumped by refresh(). Data-loading components list it as an effect dependency to re-fetch. */
  version: number;
  refresh: () => void;
};

/** Also read by the inline script in app/layout.tsx, which applies the theme before first paint. */
export const THEME_KEY = "labfactory.theme";
export const SAMPLE_LAB_ID = "emory-biophys";

const ClientContext = createContext<ClientValue | null>(null);

function chooseClient(): { client: AppClient; mode: ClientMode; labId: string } {
  // Referenced literally so Next inlines the values into the static export.
  const apiUrl = process.env.NEXT_PUBLIC_LABFACTORY_API_URL;
  if (apiUrl && apiUrl.trim() !== "") {
    const labId = process.env.NEXT_PUBLIC_LABFACTORY_LAB_ID?.trim() || SAMPLE_LAB_ID;
    return { client: createLiveClient(apiUrl.trim()), mode: "live", labId };
  }
  return { client: createSampleClient({ delayMs: 250, stepMs: 600 }), mode: "sample", labId: SAMPLE_LAB_ID };
}

// Set by setTheme, so the choice holds for this visit even when storage is unavailable.
let chosenTheme: Theme | null = null;

function storedTheme(): Theme {
  if (chosenTheme) return chosenTheme;
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

// The theme lives in localStorage and on <html>; this store lets React read it without a
// mismatch during prerendering (the server snapshot is always "system").
const themeListeners = new Set<() => void>();
function subscribeTheme(listener: () => void): () => void {
  themeListeners.add(listener);
  return () => themeListeners.delete(listener);
}

export function ClientProvider({ children }: { children: ReactNode }) {
  const [chosen] = useState(chooseClient);
  const [role, setRole] = useState<Role>("researcher");
  const [version, setVersion] = useState(0);
  const theme = useSyncExternalStore(subscribeTheme, storedTheme, () => "system" as Theme);

  const setTheme = useCallback((next: Theme) => {
    chosenTheme = next;
    applyTheme(next);
    try {
      if (next === "system") window.localStorage.removeItem(THEME_KEY);
      else window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // Storage can be unavailable (private windows); the theme still applies for this visit.
    }
    for (const listener of themeListeners) listener();
  }, []);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const value = useMemo<ClientValue>(
    () => ({ ...chosen, role, setRole, theme, setTheme, version, refresh }),
    [chosen, role, theme, setTheme, version, refresh],
  );
  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>;
}

export function useClient(): ClientValue {
  const value = useContext(ClientContext);
  if (!value) throw new Error("useClient() needs a <ClientProvider> above it.");
  return value;
}

function subscribeHash(listener: () => void): () => void {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

/** The current hash route, and a function that navigates by setting the hash. */
export function useRoute(): [Route, (route: Route) => void] {
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const route = useMemo(() => parseRoute(hash), [hash]);
  const navigate = useCallback((next: Route) => {
    window.location.hash = routeHref(next);
  }, []);
  return [route, navigate];
}
