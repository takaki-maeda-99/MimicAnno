import { useCallback, useEffect, useRef, useState } from "react";
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
  type Manifest,
  type SchemaVersion,
  type SignalsDoc,
} from "../lib/manifest";
import { selectRun, type RunSelection } from "../lib/runSelection";
import { fetchRetry } from "../lib/fetchRetry";
import { useApiToggle } from "../lib/ApiToggleContext";
import {
  patchSegmentPhase,
  runNameFromManifestUrl,
  type PatchResult,
} from "../lib/editClient";
import { patchBoundaryFrame } from "../lib/boundaryClient";
import { patchReviewed } from "../lib/reviewedClient";
import { patchLabels } from "../lib/labelsClient";
import { loadLabelset, type LabelSetDoc } from "../lib/labelsetClient";
import SegmentTable, { type SegmentTableToast, type LabelsEditPayload } from "./SegmentTable";
import VideoPlayer from "./VideoPlayer";
import Timeline from "./Timeline";
import TimelineRuler from "./TimelineRuler";
import WaveformView from "./WaveformView";

type ArtifactSlot<T> =
  | { kind: "loading" }
  | { kind: "ok"; data: T }
  | { kind: "error"; message: string };

type Loaded = {
  selection: RunSelection;
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

type Props = { episodeId: string; runHashShort: string | undefined; runSet?: string };

export default function RunViewer({ episodeId, runHashShort, runSet }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const { apiBase, apiEnabled } = useApiToggle();
  // S-RS: append ?run_set= to all artifact fetches when a run-set is selected.
  const runSetQs = runSet && runSet !== "." ? `?run_set=${encodeURIComponent(runSet)}` : "";
  const [labelset, setLabelset] = useState<LabelSetDoc | null>(null);
  const [editInFlight, setEditInFlight] = useState(false);
  const [boundaryPatchInFlight, setBoundaryPatchInFlight] = useState(false);
  const [reviewedPatchInFlight, setReviewedPatchInFlight] = useState(false);
  const [labelsPatchInFlight, setLabelsPatchInFlight] = useState(false);
  const [staleRun, setStaleRun] = useState(false);
  const [toast, setToast] = useState<SegmentTableToast | undefined>(undefined);

  useEffect(() => {
    if (!apiEnabled) return;
    let cancelled = false;
    loadLabelset(apiBase)
      .then((doc) => {
        if (!cancelled) setLabelset(doc);
      })
      .catch(() => {
        // Non-fatal: SegmentTable falls back to read-only when labelset=null.
        if (!cancelled) setLabelset(null);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, apiEnabled]);
  const abortRef = useRef<AbortController | null>(null);
  const editStartRef = useRef<number | null>(null);
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [widthPx, setWidthPx] = useState(0);
  const obsRef = useRef<ResizeObserver | null>(null);

  // Callback ref so the observer attaches when the loaded branch's <div>
  // mounts (not at RunViewer mount, which happens during the "loading" state
  // when the div doesn't exist yet — that's why a useEffect([],...) on a
  // useRef would silently never fire and Timeline/WaveformView would render
  // null forever).
  const rowRef = useCallback((node: HTMLDivElement | null) => {
    obsRef.current?.disconnect();
    obsRef.current = null;
    if (node) {
      const obs = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect.width ?? 0;
        if (w > 0) setWidthPx(w);
      });
      obs.observe(node);
      obsRef.current = obs;
    }
  }, []);

  useEffect(() => {
    setCurrentTimeSec(0);
  }, [episodeId, runHashShort]);

  // T13.10: PATCH callback. Single-in-flight guarded by editInFlight; on
  // 200 we update manifest.run_hash to the response ETag and re-fetch
  // annotation.json so server-recomputed overall_confidence + appended
  // smoothing_ops "edited" + reviewer_id show up in the table. On 412
  // we set staleRun (sticky until reload) and toast. editInFlight is
  // cleared in a finally so a thrown error or aborted re-fetch can't
  // wedge the UI.
  const onPhaseEdit = async (
    segmentId: string,
    newPhase: string,
    _oldPhase: string,
  ): Promise<PatchResult> => {
    if (state.kind !== "loaded") {
      return {
        kind: "error",
        httpStatus: 0,
        errorCode: null,
        message: "viewer not loaded",
      };
    }
    const data = state.data;
    const durationMs =
      editStartRef.current !== null
        ? Math.round(Date.now() - editStartRef.current)
        : null;
    editStartRef.current = null;
    setEditInFlight(true);
    setToast(undefined);
    let result: PatchResult;
    try {
      const runName = runNameFromManifestUrl(data.manifestUrl);
      result = await patchSegmentPhase({
        apiBase,
        runName,
        segmentId,
        newPhase,
        ifMatchRunHash: data.manifest.run_hash,
        runSet,
        clientEditDurationMs: durationMs,
      });
      if (result.kind === "ok") {
        const newManifest = { ...data.manifest, run_hash: result.runHash };
        setState((prev) =>
          prev.kind === "loaded"
            ? {
                kind: "loaded",
                data: { ...prev.data, manifest: newManifest },
              }
            : prev,
        );
        // Edits rewrite the manifest's run_hash. If the URL came in with
        // an explicit ?hash=<old_short>, it now refers to a hash that's
        // no longer in index.json — reload would surface "no run for
        // episode_id=X hash=<old>". Bring the URL back in sync via
        // history.replaceState (no entry pushed to the history stack,
        // so the browser's back button still works).
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          if (url.searchParams.has("hash")) {
            const PREFIX = "sha256:";
            const SHORT_LEN = 12;
            const stripped = result.runHash.startsWith(PREFIX)
              ? result.runHash.slice(PREFIX.length)
              : result.runHash;
            url.searchParams.set("hash", stripped.slice(0, SHORT_LEN));
            window.history.replaceState(null, "", url.toString());
          }
        }
        // Re-fetch annotation.json to pick up server-recomputed fields.
        try {
          const annUrl = resolveUrl(
            data.manifestUrl,
            artifactUrl(newManifest, "annotation"),
          ) + runSetQs;
          const r = await fetchRetry(annUrl);
          if (r.ok) {
            const ann = (await r.json()) as AnnotationResult;
            setState((prev) =>
              prev.kind === "loaded"
                ? {
                    kind: "loaded",
                    data: {
                      ...prev.data,
                      annotation: { kind: "ok", data: ann },
                    },
                  }
                : prev,
            );
          } else {
            setToast({
              level: "sync_warning",
              message: "saved, but local view may be stale (refetch failed)",
            });
          }
        } catch {
          setToast({
            level: "sync_warning",
            message: "saved, but local view may be stale (refetch failed)",
          });
        }
      } else if (result.kind === "conflict") {
        setStaleRun(true);
        setToast({
          level: "conflict",
          message: `${result.errorCode}: ${result.serverMessage}`,
        });
      } else if (result.kind === "invalid") {
        setToast({
          level: "invalid",
          message: `${result.errorCode}: ${result.serverMessage}`,
        });
      } else if (result.kind === "not_found") {
        setToast({
          level: "error",
          message: `${result.errorCode}: ${result.serverMessage}`,
        });
      } else {
        // Spec §3.5: the toast must surface the server's `error` envelope
        // code, not a generic "HTTP 500: …". The PatchResult.error variant
        // carries errorCode (may be null if the response body wasn't a
        // valid envelope — fall back to httpStatus in that case).
        const prefix =
          result.errorCode !== null
            ? result.errorCode
            : `HTTP ${result.httpStatus}`;
        setToast({
          level: "error",
          message: `${prefix}: ${result.message}`,
        });
      }
    } catch (e) {
      result = {
        kind: "error",
        httpStatus: 0,
        errorCode: null,
        message: e instanceof Error ? e.message : String(e),
      };
      setToast({ level: "error", message: result.message });
    } finally {
      setEditInFlight(false);
    }
    return result;
  };

  const onBoundaryDragCommit = async (
    boundaryId: string,
    newFrame: number,
  ): Promise<void> => {
    if (state.kind !== "loaded") return;
    const data = state.data;
    setBoundaryPatchInFlight(true);
    setToast(undefined);
    try {
      const runName = runNameFromManifestUrl(data.manifestUrl);
      const result = await patchBoundaryFrame({
        apiBase,
        runName,
        boundaryId,
        newFrame,
        ifMatchRunHash: data.manifest.run_hash,
      });
      if (result.kind === "ok") {
        const newManifest = { ...data.manifest, run_hash: result.runHash };
        setState((prev) =>
          prev.kind === "loaded"
            ? { kind: "loaded", data: { ...prev.data, manifest: newManifest } }
            : prev,
        );
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          if (url.searchParams.has("hash")) {
            const PREFIX = "sha256:";
            const SHORT_LEN = 12;
            const stripped = result.runHash.startsWith(PREFIX)
              ? result.runHash.slice(PREFIX.length)
              : result.runHash;
            url.searchParams.set("hash", stripped.slice(0, SHORT_LEN));
            window.history.replaceState(null, "", url.toString());
          }
        }
        try {
          const annUrl = resolveUrl(
            data.manifestUrl,
            artifactUrl(newManifest, "annotation"),
          );
          const r = await fetchRetry(annUrl);
          if (r.ok) {
            const ann = (await r.json()) as AnnotationResult;
            setState((prev) =>
              prev.kind === "loaded"
                ? { kind: "loaded", data: { ...prev.data, annotation: { kind: "ok", data: ann } } }
                : prev,
            );
          } else {
            setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
          }
        } catch {
          setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
        }
      } else if (result.kind === "conflict") {
        setStaleRun(true);
        setToast({ level: "conflict", message: `${result.errorCode}: ${result.serverMessage}` });
      } else if (result.kind === "invalid") {
        setToast({ level: "invalid", message: `${result.errorCode}: ${result.serverMessage}` });
      } else if (result.kind === "not_found") {
        setToast({ level: "error", message: `${result.errorCode}: ${result.serverMessage}` });
      } else {
        const prefix = result.errorCode !== null ? result.errorCode : `HTTP ${result.httpStatus}`;
        setToast({ level: "error", message: `${prefix}: ${result.message}` });
      }
    } catch (e) {
      setToast({ level: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBoundaryPatchInFlight(false);
    }
  };

  const onReviewedToggle = async (
    segmentId: string,
    newReviewed: boolean,
  ) => {
    if (state.kind !== "loaded") return { kind: "error" as const, httpStatus: 0, errorCode: null, message: "not loaded" };
    const data = state.data;
    const reviewedDurationMs =
      editStartRef.current !== null
        ? Math.round(Date.now() - editStartRef.current)
        : null;
    editStartRef.current = null;
    setReviewedPatchInFlight(true);
    setToast(undefined);
    let result;
    try {
      const runName = runNameFromManifestUrl(data.manifestUrl);
      result = await patchReviewed({
        apiBase,
        runName,
        segmentId,
        reviewed: newReviewed,
        ifMatchRunHash: data.manifest.run_hash,
        clientEditDurationMs: reviewedDurationMs,
      });
      if (result.kind === "ok") {
        const newManifest = { ...data.manifest, run_hash: result.runHash };
        setState((prev) =>
          prev.kind === "loaded"
            ? { kind: "loaded", data: { ...prev.data, manifest: newManifest } }
            : prev,
        );
        try {
          const annUrl = resolveUrl(
            data.manifestUrl,
            artifactUrl(newManifest, "annotation"),
          );
          const r = await fetchRetry(annUrl);
          if (r.ok) {
            const ann = (await r.json()) as AnnotationResult;
            setState((prev) =>
              prev.kind === "loaded"
                ? { kind: "loaded", data: { ...prev.data, annotation: { kind: "ok", data: ann } } }
                : prev,
            );
          } else {
            setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
          }
        } catch {
          setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
        }
      } else if (result.kind === "conflict") {
        setStaleRun(true);
        setToast({ level: "conflict", message: `${result.errorCode}: ${result.serverMessage}` });
      } else if (result.kind === "no_change") {
        // no-op: server said already that value — no toast needed, just let rollback happen
      } else if (result.kind === "invalid") {
        setToast({ level: "invalid", message: `${result.errorCode}: ${result.serverMessage}` });
      } else {
        const prefix = result.errorCode !== null ? result.errorCode : `HTTP ${result.httpStatus}`;
        setToast({ level: "error", message: `${prefix}: ${result.message}` });
      }
    } catch (e) {
      result = { kind: "error" as const, httpStatus: 0, errorCode: null, message: e instanceof Error ? e.message : String(e) };
      setToast({ level: "error", message: result.message });
    } finally {
      setReviewedPatchInFlight(false);
    }
    return result!;
  };

  const onLabelsEdit = async (
    segmentId: string,
    labels: LabelsEditPayload,
  ) => {
    if (state.kind !== "loaded") return { kind: "error" as const, httpStatus: 0, errorCode: null, message: "not loaded" };
    const data = state.data;
    const labelsDurationMs =
      editStartRef.current !== null
        ? Math.round(Date.now() - editStartRef.current)
        : null;
    editStartRef.current = null;
    setLabelsPatchInFlight(true);
    setToast(undefined);
    let result;
    try {
      const runName = runNameFromManifestUrl(data.manifestUrl);
      result = await patchLabels({
        apiBase,
        runName,
        segmentId,
        verb: labels.verb,
        object: labels.object,
        target: labels.target,
        failure_flags: labels.failure_flags,
        ifMatchRunHash: data.manifest.run_hash,
        clientEditDurationMs: labelsDurationMs,
      });
      if (result.kind === "ok") {
        const newManifest = { ...data.manifest, run_hash: result.runHash };
        setState((prev) =>
          prev.kind === "loaded"
            ? { kind: "loaded", data: { ...prev.data, manifest: newManifest } }
            : prev,
        );
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          if (url.searchParams.has("hash")) {
            const PREFIX = "sha256:";
            const SHORT_LEN = 12;
            const stripped = result.runHash.startsWith(PREFIX)
              ? result.runHash.slice(PREFIX.length)
              : result.runHash;
            url.searchParams.set("hash", stripped.slice(0, SHORT_LEN));
            window.history.replaceState(null, "", url.toString());
          }
        }
        try {
          const annUrl = resolveUrl(
            data.manifestUrl,
            artifactUrl(newManifest, "annotation"),
          ) + runSetQs;
          const r = await fetchRetry(annUrl);
          if (r.ok) {
            const ann = (await r.json()) as AnnotationResult;
            setState((prev) =>
              prev.kind === "loaded"
                ? { kind: "loaded", data: { ...prev.data, annotation: { kind: "ok", data: ann } } }
                : prev,
            );
          } else {
            setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
          }
        } catch {
          setToast({ level: "sync_warning", message: "saved, but local view may be stale (refetch failed)" });
        }
      } else if (result.kind === "conflict") {
        setStaleRun(true);
        setToast({ level: "conflict", message: `${result.errorCode}: ${result.serverMessage}` });
      } else if (result.kind === "no_change") {
        // no-op: server said already that value — no toast needed, let rollback happen
      } else if (result.kind === "invalid") {
        setToast({ level: "invalid", message: `${result.errorCode}: ${result.serverMessage}` });
      } else {
        const prefix = result.errorCode !== null ? result.errorCode : `HTTP ${result.httpStatus}`;
        setToast({ level: "error", message: `${prefix}: ${result.message}` });
      }
    } catch (e) {
      result = { kind: "error" as const, httpStatus: 0, errorCode: null, message: e instanceof Error ? e.message : String(e) };
      setToast({ level: "error", message: result.message });
    } finally {
      setLabelsPatchInFlight(false);
    }
    return result!;
  };

  const setVideoError = (message: string) => {
    setState((prev) =>
      prev.kind === "loaded" ? { kind: "loaded", data: { ...prev.data, videoError: message } } : prev,
    );
  };

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ kind: "loading" });

    (async () => {
      try {
        const r = await fetch(`${apiBase}index.json${runSetQs}`, { signal: controller.signal });
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
          new URL(`${apiBase}index.json`, window.location.origin).toString(),
          entry.manifest_url,
        );
        const manifestResp = await fetchRetry(manifestUrl + runSetQs, { signal: controller.signal });
        const manifest = (await manifestResp.json()) as Manifest;

        assertConsumerCapability(manifest, SUPPORTED_MAJORS);

        if (controller.signal.aborted) return;
        const initial: Loaded = {
          selection,
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
            const url = resolveUrl(manifestUrl, artifactUrl(manifest, role)) + runSetQs;
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
  }, [episodeId, runHashShort, apiBase, runSetQs]);

  if (state.kind === "loading") return <div>loading…</div>;
  if (state.kind === "error") return <div className="error">{state.message}</div>;
  // Build back-link preserving api mode and run_set selection.
  const runSetSuffix =
    runSet && runSet !== "." ? `&run_set=${encodeURIComponent(runSet)}` : "";
  const backHref = apiEnabled ? `/?api=1${runSetSuffix}` : "/";

  if (state.kind === "no-match") {
    const { episodeId: e, runHashShort: h } = state;
    return (
      <div className="error">
        {h !== undefined
          ? `no run for episode_id=${e} hash=${h}`
          : `no run for episode_id=${e}`}
        {" "}
        <a href={backHref}>all runs</a>
      </div>
    );
  }
  const { selection, manifest } = state.data;
  return (
    <div className="run-viewer">
      <div className="back-link">
        <a href={backHref}>← runs</a>
      </div>
      {selection.kind === "multiple" && (
        <ChooserBanner selection={selection} episodeId={episodeId} runSet={runSet} />
      )}
      {manifest.pipeline_status.degraded_from_phase !== null && (
        <div className="pipeline-status-banner">
          degraded from phase {manifest.pipeline_status.degraded_from_phase}: {manifest.pipeline_status.degrade_reason}
        </div>
      )}
      <div ref={rowRef} className="x-row">
        {state.data.videoError !== null
          ? <div className="error">{state.data.videoError}</div>
          : <VideoPlayer
              videoUrl={resolveUrl(state.data.manifestUrl, artifactUrl(state.data.manifest, "video"))}
              currentTimeSec={currentTimeSec}
              onTimeChange={setCurrentTimeSec}
              onError={setVideoError}
            />
        }
        {state.data.annotation.kind === "error" && (
          <div className="error">{state.data.annotation.message}</div>
        )}
        {state.data.boundaries.kind === "error" && (
          <div className="error">{state.data.boundaries.message}</div>
        )}
        {state.data.boundaries.kind === "ok" && state.data.annotation.kind === "ok" && (
          <Timeline
            widthPx={widthPx}
            durationSec={state.data.manifest.duration_sec}
            currentTimeSec={currentTimeSec}
            candidates={state.data.boundaries.data.candidates}
            segments={state.data.annotation.data.segments}
            onSeek={setCurrentTimeSec}
          />
        )}
        {state.data.signals.kind === "error" && (
          <div className="error">{state.data.signals.message}</div>
        )}
        {state.data.signals.kind === "ok" && (
          <WaveformView
            widthPx={widthPx}
            durationSec={state.data.manifest.duration_sec}
            currentTimeSec={currentTimeSec}
            channels={state.data.signals.data.channels}
          />
        )}
      </div>
      {apiEnabled && state.data.annotation.kind === "ok" && (
        <TimelineRuler
          widthPx={widthPx}
          segments={state.data.annotation.data.segments}
          fps={state.data.manifest.fps}
          pendingPatch={editInFlight || boundaryPatchInFlight || reviewedPatchInFlight || labelsPatchInFlight}
          onDragCommit={onBoundaryDragCommit}
        />
      )}
      {state.data.annotation.kind === "ok" && (
        <SegmentTable
          segments={state.data.annotation.data.segments}
          apiEnabled={apiEnabled}
          labelset={labelset}
          onPhaseEdit={onPhaseEdit}
          onReviewedToggle={onReviewedToggle}
          onLabelsEdit={onLabelsEdit}
          onEditFocus={() => { editStartRef.current = Date.now(); }}
          editInFlight={editInFlight || boundaryPatchInFlight || reviewedPatchInFlight || labelsPatchInFlight}
          staleRun={staleRun}
          toast={toast}
        />
      )}
    </div>
  );
}

function ChooserBanner({
  selection,
  episodeId,
  runSet,
}: {
  selection: Extract<RunSelection, { kind: "multiple" }>;
  episodeId: string;
  runSet?: string;
}) {
  const { apiEnabled } = useApiToggle();
  const apiSuffix = apiEnabled ? "&api=1" : "";
  const runSetSuffix =
    runSet && runSet !== "." ? `&run_set=${encodeURIComponent(runSet)}` : "";
  const all = [selection.chosen, ...selection.alternatives];
  return (
    <div className="chooser-banner">
      {all.length} runs exist for this episode. currently:{" "}
      <code>{selection.chosen.run_hash_short}</code>{" "}
      <select
        defaultValue={selection.chosen.run_hash_short}
        onChange={(e) => {
          window.location.search =
            `?run=${encodeURIComponent(episodeId)}&hash=${e.target.value}${apiSuffix}${runSetSuffix}`;
        }}
      >
        {all.map((entry) => (
          <option key={entry.run_hash_short} value={entry.run_hash_short}>
            {entry.run_hash_short}
            {" · cfg "}{entry.config_hash_short}
            {" · in "}{entry.input_hash_short}
            {" · "}{entry.generated_at}
            {" · "}{entry.task_text}
          </option>
        ))}
      </select>
    </div>
  );
}
