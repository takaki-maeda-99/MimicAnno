import { useEffect, useState } from "react";
import { useApiToggle } from "../lib/ApiToggleContext";
import { assertIndexSchema, SUPPORTED_MAJORS, type IndexDoc } from "../lib/manifest";
import type { HandIndexDoc } from "../lib/handsClient";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; doc: IndexDoc };

type HandState =
  | { kind: "loading" }
  | { kind: "hidden" }
  | { kind: "ok"; doc: HandIndexDoc };

export default function RunList() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [handState, setHandState] = useState<HandState>({ kind: "loading" });
  const { apiBase, apiEnabled } = useApiToggle();
  // Preserve ?api=1 across navigation so clicking a run from the list
  // stays in API mode (otherwise the viewer would silently fall back to
  // static /runs/index.json which may not exist in dev environments).
  const apiSuffix = apiEnabled ? "&api=1" : "";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${apiBase}index.json`);
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
  }, [apiBase]);

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
      <table>
        <thead>
          <tr>
            <th>episode</th>
            <th>run_hash</th>
            <th>generated_at</th>
            <th>task</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => (
            <tr key={`${e.episode_id}__${e.run_hash}`}>
              <td>
                <a href={`?run=${encodeURIComponent(e.episode_id)}&hash=${e.run_hash_short}${apiSuffix}`}>
                  {e.episode_id}
                </a>
              </td>
              <td><code>{e.run_hash_short}</code></td>
              <td>{e.generated_at}</td>
              <td>{e.task_text}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {handState.kind === "ok" && handState.doc.episodes.length > 0 && (
        <div className="hand-episode-list">
          <h2>手のデータ</h2>
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
                  <span className="hand-no-signals-label">(signals未生成)</span>
                </li>
              ),
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
