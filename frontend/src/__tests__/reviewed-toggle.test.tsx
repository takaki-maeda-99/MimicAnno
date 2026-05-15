/**
 * Phase 5 B r3 T8 — reviewed toggle vitest cases (spec §6.2).
 *
 * Case 1: checkbox click (false→true) → onReviewedToggle("seg-b", true)
 * Case 2: editable=false → no checkbox, read-only "✓"/"–"
 * Case 3: disabled=true → checkbox disabled
 * Case 4: 412 → conflict toast in RunViewer
 * Case 5: no_change 400 → rollback (localReviewed reverts)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import SegmentTable from "../components/SegmentTable";
import RunViewer from "../components/RunViewer";
import { ApiToggleProvider } from "../lib/ApiToggleContext";
import { __resetLabelsetCacheForTests } from "../lib/labelsetClient";

// ---------------------------------------------------------------------------
// reviewedClient mock — top-level so Vitest can hoist it
// ---------------------------------------------------------------------------

vi.mock("../lib/reviewedClient", () => ({
  patchReviewed: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Shared segment fixture
// ---------------------------------------------------------------------------

function makeSeg(id: string, reviewed = false) {
  return {
    segment_id: id,
    episode_id: "ep0",
    start_frame: 0,
    end_frame: 29,
    start_time: 0,
    end_time: 1,
    phase: "idle",
    verb: null,
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
    reviewed,
    reviewer_id: null,
  };
}

const LABELSET = { labels: [{ id: "idle" }, { id: "pick" }], labels_yaml_sha256: "sha256:" + "c".repeat(64) };

const SEGS = [makeSeg("seg-a", false), makeSeg("seg-b", false)];

// ---------------------------------------------------------------------------
// Case 1: checkbox click → onReviewedToggle called with (segmentId, true)
// ---------------------------------------------------------------------------

describe("SegmentTable — reviewed checkbox interaction", () => {
  it("checkbox false→true click → onReviewedToggle('seg-b', true)", async () => {
    const onReviewedToggle = vi.fn().mockResolvedValue({ kind: "ok", runHash: "sha256:" + "a".repeat(64), manifest: {} });
    const onPhaseEdit = vi.fn();

    render(
      <SegmentTable
        segments={SEGS}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={onPhaseEdit}
        onReviewedToggle={onReviewedToggle}
        editInFlight={false}
        staleRun={false}
      />,
    );

    const checkboxes = screen.getAllByRole("checkbox");
    // seg-b is the second row
    const segBCheckbox = checkboxes.find(
      (c) => c.getAttribute("aria-label")?.includes("seg-b"),
    );
    expect(segBCheckbox).toBeDefined();
    expect((segBCheckbox as HTMLInputElement).checked).toBe(false);

    await act(async () => {
      fireEvent.click(segBCheckbox!);
    });

    expect(onReviewedToggle).toHaveBeenCalledTimes(1);
    expect(onReviewedToggle).toHaveBeenCalledWith("seg-b", true);
  });

  // -------------------------------------------------------------------------
  // Case 2: editable=false → no checkboxes, read-only text
  // -------------------------------------------------------------------------

  it("apiEnabled=false → no checkboxes, shows '–' text", () => {
    render(
      <SegmentTable
        segments={SEGS}
        apiEnabled={false}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        editInFlight={false}
        staleRun={false}
      />,
    );

    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    // Both segments reviewed=false → "–" spans
    const spans = screen.getAllByText("–");
    expect(spans.length).toBeGreaterThanOrEqual(2);
  });

  // -------------------------------------------------------------------------
  // Case 3: disabled=true → checkboxes rendered but disabled
  // -------------------------------------------------------------------------

  it("editInFlight=true → checkboxes are disabled", () => {
    render(
      <SegmentTable
        segments={SEGS}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={vi.fn()}
        editInFlight={true}
        staleRun={false}
      />,
    );

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
    checkboxes.forEach((cb) => {
      expect((cb as HTMLInputElement).disabled).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // Case 5: no_change → localReviewed rolls back
  // -------------------------------------------------------------------------

  it("no_change result → localReviewed rolls back to original value", async () => {
    const onReviewedToggle = vi.fn().mockResolvedValue({ kind: "no_change", serverMessage: "already false" });

    render(
      <SegmentTable
        segments={[makeSeg("seg-a", false)]}
        apiEnabled={true}
        labelset={LABELSET as never}
        onPhaseEdit={vi.fn()}
        onReviewedToggle={onReviewedToggle}
        editInFlight={false}
        staleRun={false}
      />,
    );

    const cb = screen.getByRole("checkbox", { name: /seg-a/ });
    expect((cb as HTMLInputElement).checked).toBe(false);

    await act(async () => {
      fireEvent.click(cb);
    });

    // After rollback, checkbox is false again
    await waitFor(() => {
      expect((cb as HTMLInputElement).checked).toBe(false);
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
  segments: [makeSeg("seg-a", false), makeSeg("seg-b", false)],
  boundaries_url: "boundaries.json", signals_url: "signals.json", notes: null,
};

function jsonResp(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
}

describe("RunViewer — reviewed 412 → conflict toast", () => {
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

  it("reviewed PATCH 412 → etag_mismatch toast", async () => {
    const { patchReviewed } = await import("../lib/reviewedClient");
    vi.mocked(patchReviewed).mockResolvedValue({
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

    // Wait for annotation + labelset → checkboxes appear
    await waitFor(() => {
      expect(screen.queryAllByRole("checkbox").length).toBeGreaterThan(0);
    });

    const checkboxes = screen.getAllByRole("checkbox");
    const segACheckbox = checkboxes.find(
      (c) => c.getAttribute("aria-label")?.includes("seg-a"),
    );
    expect(segACheckbox).toBeDefined();

    await act(async () => {
      fireEvent.click(segACheckbox!);
    });

    await waitFor(() => {
      const alert = screen.queryByRole("alert");
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain("etag_mismatch");
    });
  });
});
