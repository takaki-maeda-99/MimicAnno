/**
 * Phase 5 B r1 T12 — frontend ApiToggle wiring.
 *
 * When `?api=1` is in the URL, the viewer fetches from /api/runs/...
 * (Phase 5 A HTTP backend) instead of the static /runs/... files. The
 * toggle also gates whether T13's editable phase dropdown renders.
 *
 * Provider takes `apiEnabled` as an explicit prop so tests don't have
 * to mock `window.location`; App.tsx is the single place that reads
 * `URLSearchParams(window.location.search).get("api")`.
 *
 * `apiBase` always ends with "/" so callers can do `${apiBase}index.json`
 * or `${apiBase}<name>/manifest.json` consistently.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";

export interface ApiToggleValue {
  apiEnabled: boolean;
  apiBase: string;
}

const DEFAULT: ApiToggleValue = {
  apiEnabled: false,
  apiBase: "/runs/",
};

const ApiToggleContext = createContext<ApiToggleValue>(DEFAULT);

export function ApiToggleProvider({
  apiEnabled,
  children,
}: {
  apiEnabled: boolean;
  children: ReactNode;
}): React.ReactElement {
  const value = useMemo<ApiToggleValue>(
    () => ({
      apiEnabled,
      apiBase: apiEnabled ? "/api/runs/" : "/runs/",
    }),
    [apiEnabled],
  );
  return (
    <ApiToggleContext.Provider value={value}>
      {children}
    </ApiToggleContext.Provider>
  );
}

export function useApiToggle(): ApiToggleValue {
  return useContext(ApiToggleContext);
}
