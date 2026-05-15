/**
 * Phase 5 B r4 T8 — labels-field edit vitest cases (spec §6.2).
 *
 * Case 1: blur with changed verb value → onLabelsEdit called
 * Case 2: no change on blur → onLabelsEdit NOT called
 * Case 3: editable=false → no inputs, static text
 * Case 4: RunViewer 412 → conflict toast
 * Case 5: no_change result → rollback (local state reverts)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import SegmentTable from "../components/SegmentTable";
import RunViewer from "../components/RunViewer";
import { ApiToggleProvider } from "../lib/ApiToggleContext";
import { __resetLabelsetCacheForTests } from "../lib/labelsetClient";

// ---------------------------------------------------------------------------
// labelsClient mock — top-level so Vitest can hoist it
// ---------------------------------------------------------------------------

vi.mock("../lib/labelsClient", () => ({
  patchLabels: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Shared segment fixture
// ---------------------------------------------------------------------------

function makeSeg(id: string, verb: string | null = null) {
  return {
    segment_id: id,
    episode_id: "ep0",
    start_frame: 0,
    end_frame: 29,
    start_time: 0,
    end_time: 1,
    phase: "idle",
    verb,
    object: null,
    target: null,
    failure_flags: [],
    label_source: "vlm",
    object_state_unavailable: false,
    object_track_ids: [],
    label_version: "1.0.0",
    start_boundary: { candidate_id: null, time: 0, sources: ["zc"], score: 0.9 },
    end_boundary: { candidate_id: null, time: 1, sources: ["zc"], score: 0.9 },
    boundary_confidence: 0.9,
    vlm_confidence: 0.8,
    overall_confidence: 0.85,
    evidence: null,
    reviewed: false,
    reviewer_id: null,
  };
}

const LABELSET = { labels: [{ id: "idle" }, { id: "pick" }], labels_yaml_sha256: "sha256:" + "c".repeat(64) };

const SEGS = [makeSeg("seg-a"), makeSeg("seg-b")];

// ---------------------------------------------------------------------------
// Case 1: blur with changed verb value → onLabelsEdit called
// ---------------------------------------------------------------------------

describe("SegmentTable — labels text input blur interaction", () => {
  it("blur with changed verb → onLabelsEdit called with correct args", async () => {
    const onLabelsEdit = vi.fn().mockResolvedValue({
      kind: "ok",
      runHash: "sha256:" + "a".repeat(64),
      manifest: {},
    });

    render(
      <SegmentTable
        segments={SEGS}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        onLabelsEdit={onLabelsEdit}
        editInFlight={false}
        staleRun={false}
      />,
    );

    // Find the verb input for seg-a
    const verbInput = screen.getByRole("textbox", { name: /verb for seg-a/i });
    expect(verbInput).toBeDefined();
    expect((verbInput as HTMLInputElement).value).toBe("");

    // Change the value and trigger blur
    await act(async () => {
      fireEvent.change(verbInput, { target: { value: "pick" } });
      fireEvent.blur(verbInput);
    });

    expect(onLabelsEdit).toHaveBeenCalledTimes(1);
    expect(onLabelsEdit).toHaveBeenCalledWith("seg-a", {
      verb: "pick",
      object: null,
      target: null,
      failure_flags: [],
    });
  });

  // -------------------------------------------------------------------------
  // Case 2: no change on blur → onLabelsEdit NOT called
  // -------------------------------------------------------------------------

  it("blur with unchanged value → onLabelsEdit NOT called", async () => {
    const onLabelsEdit = vi.fn();

    render(
      <SegmentTable
        segments={[makeSeg("seg-a")]}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        onLabelsEdit={onLabelsEdit}
        editInFlight={false}
        staleRun={false}
      />,
    );

    // Find verb input — initial value is "" (verb=null → "")
    const verbInput = screen.getByRole("textbox", { name: /verb for seg-a/i });

    // Blur without changing value
    await act(async () => {
      fireEvent.blur(verbInput);
    });

    expect(onLabelsEdit).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Case 3: editable=false → no text inputs shown, static display
  // -------------------------------------------------------------------------

  it("apiEnabled=false → no text inputs for labels, shows static text", () => {
    render(
      <SegmentTable
        segments={[makeSeg("seg-a")]}
        apiEnabled={false}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        onLabelsEdit={vi.fn()}
        editInFlight={false}
        staleRun={false}
      />,
    );

    // No text inputs for label fields
    const textboxes = screen.queryAllByRole("textbox");
    expect(textboxes).toHaveLength(0);

    // Shows "–" for null fields (verb, object, target, flags)
    const dashes = screen.getAllByText("–");
    // At least 4 dashes: verb, object, target, flags (plus reviewed "–")
    expect(dashes.length).toBeGreaterThanOrEqual(4);
  });

  // -------------------------------------------------------------------------
  // Case 5: no_change result → local state rolls back
  // -------------------------------------------------------------------------

  it("no_change result → local verb input rolls back to original", async () => {
    const onLabelsEdit = vi.fn().mockResolvedValue({
      kind: "no_change",
      serverMessage: "already the same",
    });

    render(
      <SegmentTable
        segments={[makeSeg("seg-a")]}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        onLabelsEdit={onLabelsEdit}
        editInFlight={false}
        staleRun={false}
      />,
    );

    const verbInput = screen.getByRole("textbox", { name: /verb for seg-a/i });
    expect((verbInput as HTMLInputElement).value).toBe("");

    await act(async () => {
      fireEvent.change(verbInput, { target: { value: "pick" } });
      fireEvent.blur(verbInput);
    });

    // After rollback, input returns to original value
    await waitFor(() => {
      expect((verbInput as HTMLInputElement).value).toBe("");
    });
  });
});

// ---------------------------------------------------------------------------
// Case 4: RunViewer — 412 → conflict toast
// ---------------------------------------------------------------------------

const RUN_HASH = "sha256:" + "a".repeat(64);

const MANIFEST = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  task: { text: "task", version: null },
  generated_at: "2026-05-16T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1", pipeline_phase: 4 },
  config_hash: "cfg",
  input_hash: "inp",
  run_hash: RUN_HASH,
  model_versions: {},
  pipeline_params: {
    boundary: { weights: {}, thresholds: {}, merge_window_sec: 0, score_threshold: 0, disabled_sources: [] },
  },
  inputs: { video: { path: "v.mp4", sha256: "v" }, parquet: { path: "x.parquet", sha256: "p" } },
  time_base: "video_pts_seconds",
  fps: 30,
  duration_sec: 1.0,
  pipeline_status: { object_state_available: false, degraded_from_phase: null, degrade_reason: null },
  compat: { manifest: 0, annotation: 0, boundaries: 0, signals: 0 },
  artifacts: [
    { role: "video", url: "v.mp4", content_type: "video/mp4" },
    { role: "annotation", url: "annotation.json", content_type: "application/json" },
    { role: "boundaries", url: "boundaries.json", content_type: "application/json" },
    { role: "signals", url: "signals.json", content_type: "application/json" },
  ],
};

const INDEX = {
  schema_version: "0.1.0",
  runs: [{
    episode_id: "ep0", run_hash: RUN_HASH, run_hash_short: "aaaa",
    config_hash_short: "cfg00000", input_hash_short: "inp00000",
    manifest_url: "ep0__aaaa/manifest.json", task_text: "task",
    pipeline_phase: 4, generated_at: "2026-05-16T00:00:00Z",
  }],
};

const ANNOTATION = {
  schema_version: "0.1.0", episode_id: "ep0",
  task: { text: "task", version: null },
  generated_at: "2026-05-16T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1", pipeline_phase: 4 },
  config_hash: "cfg", input_hash: "inp", run_hash: RUN_HASH,
  model_versions: {}, pipeline_phase: 4,
  pipeline_status: MANIFEST.pipeline_status,
  segments: [makeSeg("seg-a"), makeSeg("seg-b")],
  boundaries_url: "boundaries.json", signals_url: "signals.json", notes: null,
};

function jsonResp(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
}

describe("RunViewer — labels PATCH 412 → conflict toast", () => {
  beforeEach(() => {
    __resetLabelsetCacheForTests();
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("ResizeObserver", class {
      cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) { this.cb = cb; }
      observe(target: Element): void {
        this.cb(
          [{ contentRect: { width: 900 } } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      }
      unobserve(): void {}
      disconnect(): void {}
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("labels PATCH 412 → etag_mismatch conflict toast", async () => {
    const { patchLabels } = await import("../lib/labelsClient");
    vi.mocked(patchLabels).mockResolvedValue({
      kind: "conflict",
      errorCode: "etag_mismatch",
      serverMessage: "If-Match does not equal current manifest.run_hash",
    });

    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("index.json")) return jsonResp(INDEX);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST);
      if (url.endsWith("/annotation.json")) return jsonResp(ANNOTATION);
      if (url.endsWith("/boundaries.json")) return jsonResp({ schema_version: "0.1.0", episode_id: "ep0", run_hash: RUN_HASH, candidates: [] });
      if (url.endsWith("/signals.json")) return jsonResp({ schema_version: "0.1.0", episode_id: "ep0", run_hash: RUN_HASH, channels: [] });
      if (url.endsWith("/api/labelset")) return jsonResp({ labels: [{ id: "idle" }], labels_yaml_sha256: "sha256:" + "c".repeat(64) });
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    // Wait for annotation + labelset → text inputs appear
    await waitFor(() => {
      expect(screen.queryAllByRole("textbox").length).toBeGreaterThan(0);
    });

    // Find the verb input for seg-a and blur with a change
    const verbInput = screen.getByRole("textbox", { name: /verb for seg-a/i });

    await act(async () => {
      fireEvent.change(verbInput, { target: { value: "pick" } });
      fireEvent.blur(verbInput);
    });

    await waitFor(() => {
      const alert = screen.queryByRole("alert");
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain("etag_mismatch");
    });
  });
});
