import { useEffect, useState } from "react";
import { useApiToggle } from "../lib/ApiToggleContext";
import { assertIndexSchema, SUPPORTED_MAJORS, type IndexDoc } from "../lib/manifest";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; doc: IndexDoc };

export default function RunList() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const { apiBase } = useApiToggle();

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
                <a href={`?run=${encodeURIComponent(e.episode_id)}&hash=${e.run_hash_short}`}>
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
    </div>
  );
}
