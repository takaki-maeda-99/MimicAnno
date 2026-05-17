import { useEffect, useState } from "react";
import { useApiToggle } from "../lib/ApiToggleContext";
import { assertIndexSchema, SUPPORTED_MAJORS, type IndexDoc } from "../lib/manifest";
import type { HandIndexDoc } from "../lib/handsClient";
import { fetchRunSets, type RunSetEntry } from "../lib/runsClient";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; doc: IndexDoc };

type HandState =
  | { kind: "loading" }
  | { kind: "hidden" }
  | { kind: "ok"; doc: HandIndexDoc };

type Props = { runSet?: string };

export default function RunList({ runSet }: Props = {}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [handState, setHandState] = useState<HandState>({ kind: "loading" });
  const [runSets, setRunSets] = useState<RunSetEntry[]>([]);
  const { apiBase, apiEnabled } = useApiToggle();
  const apiSuffix = apiEnabled ? "&api=1" : "";

  // Build ?run_set= query param for all api fetches.
  const runSetQs =
    runSet && runSet !== "." ? `?run_set=${encodeURIComponent(runSet)}` : "";

  // In api mode, fetch available run-sets once for the switcher dropdown.
  useEffect(() => {
    if (!apiEnabled) return;
    fetchRunSets()
      // Hide run-sets whose name starts with "_" (smoke / scratch).
      .then((rs) => setRunSets(rs.filter((r) => !r.name.startsWith("_"))))
      .catch(() => setRunSets([]));
  }, [apiEnabled]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        let r = await fetch(`${apiBase}index.json${runSetQs}`);
        // The top-level static runs/index.json is synthesized by the
        // backend, not written to disk. When static mode 404s, retry
        // via the API endpoint so navigating back to "/" still works
        // as long as `mimicanno serve` is running.
        if (!apiEnabled && r.status === 404) {
          const apiR = await fetch(`/api/runs/index.json${runSetQs}`);
          if (apiR.ok) r = apiR;
        }
        if (r.status === 404) {
          if (!cancelled) {
            setState({
              kind: "error",
              message:
                "runs/index.json not reachable (HTTP 404). check that the dev server is running and that mimicanno annotate has produced a run.",
            });
          }
          return;
        }
        if (!r.ok) {
          if (!cancelled) {
            setState({ kind: "error", message: `failed to load index.json: HTTP ${r.status}` });
          }
          return;
        }
        const doc = (await r.json()) as IndexDoc;
        assertIndexSchema(doc, SUPPORTED_MAJORS.index);
        if (!cancelled) setState({ kind: "ok", doc });
      } catch (err) {
        if (!cancelled) {
          setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase, runSetQs]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/hands/index.json");
        if (!r.ok) {
          if (!cancelled) setHandState({ kind: "hidden" });
          return;
        }
        const doc = (await r.json()) as HandIndexDoc;
        if (!cancelled) setHandState({ kind: "ok", doc });
      } catch {
        if (!cancelled) setHandState({ kind: "hidden" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const showSwitcher = apiEnabled && runSets.length > 1;

  if (state.kind === "loading") return <div>loading…</div>;
  if (state.kind === "error") return <div className="error">{state.message}</div>;
  if (state.doc.runs.length === 0) {
    return <div>no runs yet. run `mimicanno annotate` to produce one.</div>;
  }
  const sorted = [...state.doc.runs].sort((a, b) =>
    a.generated_at < b.generated_at ? 1 : -1,
  );
  return (
    <div className="run-list">
      <h1>runs</h1>
      {showSwitcher && (
        <div className="run-set-switcher">
          <label htmlFor="run-set-select">run-set: </label>
          <select
            id="run-set-select"
            value={runSet ?? "."}
            onChange={(e) => {
              const selected = e.target.value;
              const next = new URLSearchParams(window.location.search);
              if (selected === ".") {
                next.delete("run_set");
              } else {
                next.set("run_set", selected);
              }
              window.location.search = next.toString();
            }}
          >
            {runSets.map((rs) => (
              <option key={rs.name} value={rs.name}>
                {rs.label}
              </option>
            ))}
          </select>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>episode</th>
            <th>run_set</th>
            <th>run_hash</th>
            <th>generated_at</th>
            <th>task</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => {
            // Prefer row-level run_set (merged-mode); fall back to global runSet.
            const rowRunSet = e.run_set ?? runSet;
            const rowRunSetNav =
              rowRunSet && rowRunSet !== "."
                ? `&run_set=${encodeURIComponent(rowRunSet)}`
                : "";
            return (
              <tr key={`${e.episode_id}__${e.run_hash}`}>
                <td>
                  <a href={`?run=${encodeURIComponent(e.episode_id)}&hash=${e.run_hash_short}${apiSuffix}${rowRunSetNav}`}>
                    {e.episode_id}
                  </a>
                </td>
                <td>{e.run_set ?? "—"}</td>
                <td><code>{e.run_hash_short}</code></td>
                <td>{e.generated_at}</td>
                <td>{e.task_text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {handState.kind === "ok" && handState.doc.episodes.length > 0 && (
        <div className="hand-episode-list">
          <h2>Hand data</h2>
          <ul>
            {handState.doc.episodes.map((ep) =>
              ep.signals_ready ? (
                <li key={ep.episode_id}>
                  <a href={`?hand=${encodeURIComponent(ep.episode_id)}&api=1`}>
                    {ep.episode_id}
                  </a>
                </li>
              ) : (
                <li key={ep.episode_id} className="hand-episode-no-signals">
                  {ep.episode_id}{" "}
                  <span className="hand-no-signals-label">(signals not generated)</span>
                </li>
              ),
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
