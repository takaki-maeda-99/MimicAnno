import { useEffect, useRef, useState } from "react";
import {
  artifactUrl,
  assertArtifactSelfConsistent,
  assertConsumerCapability,
  assertIndexSchema,
  resolveUrl,
  SUPPORTED_MAJORS,
  type AnnotationResult,
  type BoundariesDoc,
  type IndexDoc,
  type IndexEntry,
  type Manifest,
  type SchemaVersion,
  type SignalsDoc,
} from "../lib/manifest";
import { selectRun, type RunSelection } from "../lib/runSelection";
import { fetchRetry } from "../lib/fetchRetry";

type ArtifactSlot<T> =
  | { kind: "loading" }
  | { kind: "ok"; data: T }
  | { kind: "error"; message: string };

type Loaded = {
  selection: RunSelection;
  entry: IndexEntry;
  manifest: Manifest;
  manifestUrl: string;
  annotation: ArtifactSlot<AnnotationResult>;
  boundaries: ArtifactSlot<BoundariesDoc>;
  signals: ArtifactSlot<SignalsDoc>;
  videoError: string | null;
};

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "no-match"; episodeId: string; runHashShort: string | undefined }
  | { kind: "loaded"; data: Loaded };

type Props = { episodeId: string; runHashShort: string | undefined };

export default function RunViewer({ episodeId, runHashShort }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const abortRef = useRef<AbortController | null>(null);
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [widthPx, setWidthPx] = useState(0);
  const rowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!rowRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setWidthPx(w);
    });
    obs.observe(rowRef.current);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    setCurrentTimeSec(0);
  }, [episodeId, runHashShort]);

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
        const initial: Loaded = {
          selection,
          entry,
          manifest,
          manifestUrl,
          annotation: { kind: "loading" },
          boundaries: { kind: "loading" },
          signals: { kind: "loading" },
          videoError: null,
        };
        setState({ kind: "loaded", data: initial });

        const updateSlot = <K extends "annotation" | "boundaries" | "signals">(
          role: K,
          slot: Loaded[K],
        ) => {
          if (controller.signal.aborted) return;
          setState((prev) =>
            prev.kind === "loaded" ? { kind: "loaded", data: { ...prev.data, [role]: slot } } : prev,
          );
        };

        const fetchArtifact = async <T extends { schema_version: string }>(
          role: "annotation" | "boundaries" | "signals",
        ) => {
          try {
            const url = resolveUrl(manifestUrl, artifactUrl(manifest, role));
            const r = await fetch(url, { signal: controller.signal });
            if (!r.ok) {
              updateSlot(role, { kind: "error", message: `failed to load ${role}: HTTP ${r.status}` });
              return;
            }
            let data: T;
            try {
              data = (await r.json()) as T;
            } catch (e) {
              updateSlot(role, { kind: "error", message: `malformed ${role}: ${e instanceof Error ? e.message : String(e)}` });
              return;
            }
            try {
              assertArtifactSelfConsistent(role, data as { schema_version: SchemaVersion }, manifest);
            } catch (e) {
              updateSlot(role, { kind: "error", message: e instanceof Error ? e.message : String(e) });
              return;
            }
            updateSlot(role, { kind: "ok", data: data as never });
          } catch (e) {
            if (controller.signal.aborted) return;
            updateSlot(role, { kind: "error", message: e instanceof Error ? e.message : String(e) });
          }
        };

        void Promise.all([
          fetchArtifact<AnnotationResult>("annotation"),
          fetchArtifact<BoundariesDoc>("boundaries"),
          fetchArtifact<SignalsDoc>("signals"),
        ]);
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
      <div ref={rowRef} className="x-row">
        <div>video placeholder</div>
        <div>timeline placeholder (widthPx={widthPx}, t={currentTimeSec.toFixed(3)})</div>
        <div>waveform placeholder</div>
      </div>
      <div>
        {(["annotation", "boundaries", "signals"] as const).map((role) => {
          const slot = state.data[role];
          if (slot.kind === "loading") return <div key={role}>{role}: loading…</div>;
          if (slot.kind === "error") return <div key={role} className="error">{slot.message}</div>;
          return <div key={role}>{role}: ok</div>;
        })}
      </div>
    </div>
  );
}
