import { useEffect, useRef, useState } from "react";
import {
  artifactUrl,
  assertConsumerCapability,
  assertIndexSchema,
  resolveUrl,
  SUPPORTED_MAJORS,
  type IndexDoc,
  type IndexEntry,
  type Manifest,
} from "../lib/manifest";
import { selectRun, type RunSelection } from "../lib/runSelection";
import { fetchRetry } from "../lib/fetchRetry";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "no-match"; episodeId: string; runHashShort: string | undefined }
  | {
      kind: "manifest-loaded";
      selection: RunSelection;
      entry: IndexEntry;
      manifest: Manifest;
      manifestUrl: string;
    };

type Props = { episodeId: string; runHashShort: string | undefined };

export default function RunViewer({ episodeId, runHashShort }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ kind: "loading" });

    (async () => {
      try {
        const r = await fetch("/runs/index.json", { signal: controller.signal });
        if (!r.ok) {
          setState({ kind: "error", message: `failed to load index.json: HTTP ${r.status}` });
          return;
        }
        const doc = (await r.json()) as IndexDoc;
        assertIndexSchema(doc, SUPPORTED_MAJORS.index);
        const selection = selectRun(doc.runs, episodeId, runHashShort);
        if (selection.kind === "none") {
          setState({ kind: "no-match", episodeId, runHashShort });
          return;
        }
        const entry = selection.kind === "single" ? selection.entry : selection.chosen;

        const manifestUrl = resolveUrl(
          new URL("/runs/index.json", window.location.origin).toString(),
          entry.manifest_url,
        );
        const manifestResp = await fetchRetry(manifestUrl, { signal: controller.signal });
        const manifest = (await manifestResp.json()) as Manifest;

        assertConsumerCapability(manifest, SUPPORTED_MAJORS);

        if (controller.signal.aborted) return;
        setState({ kind: "manifest-loaded", selection, entry, manifest, manifestUrl });
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      }
    })();

    return () => controller.abort();
  }, [episodeId, runHashShort]);

  if (state.kind === "loading") return <div>loading…</div>;
  if (state.kind === "error") return <div className="error">{state.message}</div>;
  if (state.kind === "no-match") {
    const { episodeId: e, runHashShort: h } = state;
    return (
      <div className="error">
        {h !== undefined
          ? `no run for episode_id=${e} hash=${h}`
          : `no run for episode_id=${e}`}
        {" "}
        <a href="/">all runs</a>
      </div>
    );
  }
  return (
    <div className="run-viewer">
      <div>
        manifest loaded for <code>{state.entry.run_hash_short}</code>
        {" "}
        ({state.manifest.duration_sec.toFixed(2)}s, {state.manifest.fps.toFixed(0)} fps).
        Loading artifacts…
      </div>
    </div>
  );
}
