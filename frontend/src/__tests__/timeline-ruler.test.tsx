/**
 * Phase 5 B r2 T14 — TimelineRuler vitest cases (spec §5.3).
 *
 * Case 1: drag interaction → onDragCommit called with correct (boundaryId, newFrame).
 * Case 2: 412 on boundary PATCH → staleRun conflict toast in RunViewer.
 * Case 3: first/last segment endpoints have no handle (inner boundaries only).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import TimelineRuler from "../components/TimelineRuler";
import RunViewer from "../components/RunViewer";
import { ApiToggleProvider } from "../lib/ApiToggleContext";
import { __resetLabelsetCacheForTests } from "../lib/labelsetClient";

// ---------------------------------------------------------------------------
// boundaryClient mock — top-level so Vitest can hoist it
// ---------------------------------------------------------------------------

vi.mock("../lib/boundaryClient", () => ({
  patchBoundaryFrame: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Shared segment fixture
// ---------------------------------------------------------------------------

function makeSeg(id: string, start: number, end: number, fps = 30) {
  return {
    segment_id: id,
    episode_id: "ep0",
    start_frame: start,
    end_frame: end,
    start_time: start / fps,
    end_time: end / fps,
    phase: "idle",
    verb: null,
    object: null,
    target: null,
    failure_flags: [],
    label_source: "vlm",
    object_state_unavailable: false,
    object_track_ids: [],
    label_version: "1.0.0",
    start_boundary: { candidate_id: null, time: start / fps, sources: ["zc"], score: 0.9 },
    end_boundary: { candidate_id: null, time: end / fps, sources: ["zc"], score: 0.9 },
    boundary_confidence: 0.9,
    vlm_confidence: 0.8,
    overall_confidence: 0.85,
    evidence: null,
    reviewed: false,
    reviewer_id: null,
  };
}

// 3 segments: [0..29] [30..59] [60..89] — inner boundaries at frame 30 (seg-b) and 60 (seg-c).
const SEGS = [makeSeg("seg-a", 0, 29), makeSeg("seg-b", 30, 59), makeSeg("seg-c", 60, 89)];

// ---------------------------------------------------------------------------
// Case 1: drag → onDragCommit(boundaryId, newFrame)
// ---------------------------------------------------------------------------

// jsdom's PointerEvent does not expose clientX from the event init dict (it's
// undefined at the React handler level). Keyboard nudge tests cover the
// onDragCommit contract without needing pointer coordinates.
describe("TimelineRuler — drag commits correct (boundaryId, newFrame)", () => {
  it("ArrowRight on seg-b handle → onDragCommit('seg-b', 31)", () => {
    // seg-b.start_frame = 30; ArrowRight δ = +1 → new_frame = 31
    // clampFrame(31, left.start=0, right.end=59, total=90) = 31 ✓
    const onDragCommit = vi.fn();
    render(
      <TimelineRuler
        widthPx={900}
        segments={SEGS}
        fps={30}
        pendingPatch={false}
        onDragCommit={onDragCommit}
      />,
    );

    const handle = screen.getByRole("slider", { name: /seg-b/ });
    fireEvent.keyDown(handle, { key: "ArrowRight" });

    expect(onDragCommit).toHaveBeenCalledTimes(1);
    expect(onDragCommit).toHaveBeenCalledWith("seg-b", 31);
  });

  it("ArrowLeft on seg-b handle → onDragCommit('seg-b', 29)", () => {
    // seg-b.start_frame = 30; ArrowLeft δ = -1 → new_frame = 29
    // clampFrame(29, left.start=0, right.end=59, total=90) = 29 ✓
    const onDragCommit = vi.fn();
    render(
      <TimelineRuler
        widthPx={900}
        segments={SEGS}
        fps={30}
        pendingPatch={false}
        onDragCommit={onDragCommit}
      />,
    );

    const handle = screen.getByRole("slider", { name: /seg-b/ });
    fireEvent.keyDown(handle, { key: "ArrowLeft" });

    expect(onDragCommit).toHaveBeenCalledTimes(1);
    expect(onDragCommit).toHaveBeenCalledWith("seg-b", 29);
  });

  it("pendingPatch=true → keyboard nudge does not commit", () => {
    const onDragCommit = vi.fn();
    render(
      <TimelineRuler
        widthPx={900}
        segments={SEGS}
        fps={30}
        pendingPatch={true}
        onDragCommit={onDragCommit}
      />,
    );

    const handle = screen.getByRole("slider", { name: /seg-b/ });
    fireEvent.keyDown(handle, { key: "ArrowRight" });

    expect(onDragCommit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Case 2: RunViewer boundary 412 → conflict toast
// ---------------------------------------------------------------------------

const RUN_HASH = "sha256:" + "a".repeat(64);

const MANIFEST_3SEG = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  task: { text: "task", version: null },
  generated_at: "2026-05-14T00:00:00Z",
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
  duration_sec: 3.0,
  pipeline_status: { object_state_available: false, degraded_from_phase: null, degrade_reason: null },
  compat: { manifest: 0, annotation: 0, boundaries: 0, signals: 0 },
  artifacts: [
    { role: "video", url: "v.mp4", content_type: "video/mp4" },
    { role: "annotation", url: "annotation.json", content_type: "application/json" },
    { role: "boundaries", url: "boundaries.json", content_type: "application/json" },
    { role: "signals", url: "signals.json", content_type: "application/json" },
  ],
};

const INDEX_3SEG = {
  schema_version: "0.1.0",
  runs: [{
    episode_id: "ep0", run_hash: RUN_HASH, run_hash_short: "aaaa",
    config_hash_short: "cfg00000", input_hash_short: "inp00000",
    manifest_url: "ep0__aaaa/manifest.json", task_text: "task",
    pipeline_phase: 4, generated_at: "2026-05-14T00:00:00Z",
  }],
};

const ANNOTATION_3SEG = {
  schema_version: "0.1.0", episode_id: "ep0",
  task: { text: "task", version: null },
  generated_at: "2026-05-14T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1", pipeline_phase: 4 },
  config_hash: "cfg", input_hash: "inp", run_hash: RUN_HASH,
  model_versions: {}, pipeline_phase: 4,
  pipeline_status: MANIFEST_3SEG.pipeline_status,
  segments: SEGS,
  boundaries_url: "boundaries.json", signals_url: "signals.json", notes: null,
};

function jsonResp(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
}

describe("RunViewer — boundary PATCH 412 → conflict toast", () => {
  beforeEach(() => {
    __resetLabelsetCacheForTests();
    vi.stubGlobal("fetch", vi.fn());
    // ResizeObserver that immediately fires with width=900 so TimelineRuler renders.
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

  it("boundary 412 → etag_mismatch toast", async () => {
    const { patchBoundaryFrame } = await import("../lib/boundaryClient");
    vi.mocked(patchBoundaryFrame).mockResolvedValue({
      kind: "conflict",
      errorCode: "etag_mismatch",
      serverMessage: "If-Match does not equal current manifest.run_hash",
    });

    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("index.json")) return jsonResp(INDEX_3SEG);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST_3SEG);
      if (url.endsWith("/annotation.json")) return jsonResp(ANNOTATION_3SEG);
      if (url.endsWith("/boundaries.json")) return jsonResp({ schema_version: "0.1.0", episode_id: "ep0", run_hash: RUN_HASH, candidates: [] });
      if (url.endsWith("/signals.json")) return jsonResp({ schema_version: "0.1.0", episode_id: "ep0", run_hash: RUN_HASH, channels: [] });
      if (url.endsWith("/api/labelset")) return jsonResp({ labels: [], labels_yaml_sha256: "sha256:" + "c".repeat(64) });
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    // Wait for TimelineRuler handles to appear (annotation loaded + widthPx=900).
    await waitFor(() => {
      expect(screen.queryAllByRole("slider").length).toBeGreaterThan(0);
    });

    // Nudge a boundary via keyboard → triggers onBoundaryDragCommit → 412 mock.
    const handles = screen.getAllByRole("slider");
    const segBHandle = handles.find((h) => h.getAttribute("aria-label")?.includes("seg-b"));
    expect(segBHandle).toBeDefined();

    await act(async () => {
      fireEvent.keyDown(segBHandle!, { key: "ArrowRight" });
    });

    await waitFor(() => {
      const alert = screen.queryByRole("alert");
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain("etag_mismatch");
    });
  });
});

// ---------------------------------------------------------------------------
// Case 3: endpoint handles not shown — inner only
// ---------------------------------------------------------------------------

describe("TimelineRuler — endpoint handles not shown", () => {
  it("3-segment annotation → 2 handles (seg-b, seg-c), not seg-a", () => {
    render(
      <TimelineRuler
        widthPx={900}
        segments={SEGS}
        fps={30}
        pendingPatch={false}
        onDragCommit={vi.fn()}
      />,
    );

    const handles = screen.getAllByRole("slider");
    expect(handles).toHaveLength(2);

    const labels = handles.map((h) => h.getAttribute("aria-label") ?? "");
    expect(labels.some((l) => l.includes("seg-b"))).toBe(true);
    expect(labels.some((l) => l.includes("seg-c"))).toBe(true);
    expect(labels.some((l) => l.includes("seg-a"))).toBe(false);
  });

  it("single segment → no handles", () => {
    render(
      <TimelineRuler
        widthPx={900}
        segments={[SEGS[0]]}
        fps={30}
        pendingPatch={false}
        onDragCommit={vi.fn()}
      />,
    );
    expect(screen.queryAllByRole("slider")).toHaveLength(0);
  });
});
