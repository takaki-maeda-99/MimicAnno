/**
 * Phase 5 B r1 T13.10.5 — end-to-end PATCH wiring integration test.
 *
 * Renders the real RunViewer wrapped in ApiToggleProvider(apiEnabled=true),
 * stubs `fetch` to walk through: index → manifest → annotation → boundaries
 * → signals → labelset, then drives a phase change and asserts the captured
 * PATCH request carries the manifest's actual run_hash in `If-Match` — the
 * one piece editClient.test.ts can't prove in isolation.
 *
 * Spec §5.3 #1.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import RunViewer from "../RunViewer";
import { ApiToggleProvider } from "../../lib/ApiToggleContext";
import { __resetLabelsetCacheForTests } from "../../lib/labelsetClient";

const RUN_HASH = "sha256:" + "a".repeat(64);
const NEW_RUN_HASH = "sha256:" + "b".repeat(64);

const INDEX_DOC = {
  schema_version: "0.1.0",
  runs: [
    {
      episode_id: "ep0",
      run_hash: RUN_HASH,
      run_hash_short: "aaaaaaaa",
      config_hash_short: "cfg00000",
      input_hash_short: "inp00000",
      manifest_url: "ep0__aaaaaaaa/manifest.json",
      task_text: "pick up tape",
      pipeline_phase: 4,
      generated_at: "2026-05-14T00:00:00Z",
    },
  ],
};

const MANIFEST = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  task: { text: "pick up tape", version: null },
  generated_at: "2026-05-14T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1", pipeline_phase: 4 },
  config_hash: "cfg",
  input_hash: "inp",
  run_hash: RUN_HASH,
  model_versions: {},
  pipeline_params: {
    boundary: {
      weights: {},
      thresholds: {},
      merge_window_sec: 0,
      score_threshold: 0,
      disabled_sources: [],
    },
  },
  inputs: {
    video: { path: "video.mp4", sha256: "vid" },
    parquet: { path: "x.parquet", sha256: "pq" },
  },
  time_base: "video_pts_seconds",
  fps: 30,
  duration_sec: 1.0,
  pipeline_status: {
    object_state_available: false,
    degraded_from_phase: null,
    degrade_reason: null,
  },
  compat: { manifest: 0, annotation: 0, boundaries: 0, signals: 0 },
  artifacts: [
    { role: "video", url: "video.mp4", content_type: "video/mp4" },
    {
      role: "annotation",
      url: "annotation.json",
      content_type: "application/json",
    },
    {
      role: "boundaries",
      url: "boundaries.json",
      content_type: "application/json",
    },
    {
      role: "signals",
      url: "signals.json",
      content_type: "application/json",
    },
  ],
};

const ANNOTATION = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  task: { text: "pick up tape", version: null },
  generated_at: "2026-05-14T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1", pipeline_phase: 4 },
  config_hash: "cfg",
  input_hash: "inp",
  run_hash: RUN_HASH,
  model_versions: {},
  pipeline_phase: 4,
  pipeline_status: MANIFEST.pipeline_status,
  segments: [
    {
      segment_id: "seg-001",
      episode_id: "ep0",
      start_frame: 0,
      end_frame: 30,
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
      start_boundary: {
        candidate_id: null,
        time: 0,
        sources: ["zc"],
        score: 0.9,
      },
      end_boundary: {
        candidate_id: null,
        time: 1,
        sources: ["zc"],
        score: 0.9,
      },
      boundary_confidence: 0.9,
      vlm_confidence: 0.8,
      overall_confidence: 0.85,
      evidence: null,
      reviewed: false,
      reviewer_id: null,
    },
  ],
  boundaries_url: "boundaries.json",
  signals_url: "signals.json",
  notes: null,
};

const BOUNDARIES = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  run_hash: RUN_HASH,
  candidates: [],
};

const SIGNALS = {
  schema_version: "0.1.0",
  episode_id: "ep0",
  run_hash: RUN_HASH,
  channels: [],
};

const LABELSET = {
  labels: [
    { id: "idle", requires_object: false },
    { id: "grasp_object", requires_object: true },
  ],
  labels_yaml_sha256: "sha256:" + "c".repeat(64),
};

function jsonResp(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
}

beforeEach(() => {
  __resetLabelsetCacheForTests();
  vi.stubGlobal("fetch", vi.fn());
  // jsdom doesn't provide ResizeObserver; RunViewer uses it to size the
  // Timeline/Waveform. Stub the smallest no-op the component needs.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RunViewer integration — PATCH carries manifest.run_hash in If-Match", () => {
  it("end-to-end: select change → PATCH with correct If-Match + body", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const updatedAnnotation = {
      ...ANNOTATION,
      run_hash: NEW_RUN_HASH,
      segments: [
        {
          ...ANNOTATION.segments[0],
          phase: "grasp_object",
          reviewed: true,
          reviewer_id: "takaki",
        },
      ],
    };

    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/api/runs/index.json")) return jsonResp(INDEX_DOC);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST);
      if (url.endsWith("/annotation.json")) {
        // First call returns original; subsequent return updated.
        if (fetchMock.mock.calls.length > 4) return jsonResp(updatedAnnotation);
        return jsonResp(ANNOTATION);
      }
      if (url.endsWith("/boundaries.json")) return jsonResp(BOUNDARIES);
      if (url.endsWith("/signals.json")) return jsonResp(SIGNALS);
      if (url.endsWith("/api/labelset")) return jsonResp(LABELSET);
      if (url.includes("/segments/")) {
        return jsonResp(
          { ...MANIFEST, run_hash: NEW_RUN_HASH },
          { headers: { ETag: `"${NEW_RUN_HASH}"` } },
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    // Wait for the labelset-backed <select> to appear (annotation loaded
    // AND labelset cache resolved).
    const sel = (await screen.findByLabelText(
      "phase for seg-001",
    )) as HTMLSelectElement;
    expect(sel.value).toBe("idle");

    await act(async () => {
      fireEvent.change(sel, { target: { value: "grasp_object" } });
    });

    // Find the PATCH call.
    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
    });

    const patchCall = fetchMock.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    )!;
    const patchUrl = patchCall[0] as string;
    const patchInit = patchCall[1] as RequestInit;
    expect(patchUrl).toBe(
      "/api/runs/ep0__aaaaaaaa/segments/seg-001",
    );
    const headers = new Headers(patchInit.headers);
    // Spec §5.3 #1: the If-Match is the manifest's actual run_hash, not
    // anything hardcoded — proves end-to-end state plumbing.
    expect(headers.get("If-Match")).toBe(`"${RUN_HASH}"`);
    expect(headers.get("Content-Type")).toBe("application/json");
    const body = JSON.parse(patchInit.body as string);
    expect(body).toEqual({ phase: "grasp_object" });
    expect(Object.keys(body)).toHaveLength(1);

    // Re-fetch of annotation.json after success.
    await waitFor(() => {
      const annCalls = fetchMock.mock.calls.filter((c) => {
        const u = typeof c[0] === "string" ? c[0] : (c[0] as Request).url;
        return u.endsWith("/annotation.json");
      });
      expect(annCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});

describe("RunViewer URL hash update after PATCH (BLOCKER fix from UI smoke)", () => {
  it("after 200, history.replaceState rewrites ?hash to the new short hash", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/api/runs/index.json")) return jsonResp(INDEX_DOC);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST);
      if (url.endsWith("/annotation.json")) return jsonResp(ANNOTATION);
      if (url.endsWith("/boundaries.json")) return jsonResp(BOUNDARIES);
      if (url.endsWith("/signals.json")) return jsonResp(SIGNALS);
      if (url.endsWith("/api/labelset")) return jsonResp(LABELSET);
      if (url.includes("/segments/")) {
        return jsonResp(
          { ...MANIFEST, run_hash: NEW_RUN_HASH },
          { headers: { ETag: `"${NEW_RUN_HASH}"` } },
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const oldShort = INDEX_DOC.runs[0].run_hash_short;
    const newShort = NEW_RUN_HASH.slice("sha256:".length, "sha256:".length + 12);

    // Pre-set the URL so we can assert replaceState rewrote it.
    window.history.replaceState(null, "", `/?run=ep0&hash=${oldShort}&api=1`);

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={oldShort} />
      </ApiToggleProvider>,
    );
    const sel = (await screen.findByLabelText(
      "phase for seg-001",
    )) as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(sel, { target: { value: "grasp_object" } });
    });

    await waitFor(() => {
      expect(window.location.search).toContain(`hash=${newShort}`);
    });
    // And the original hash is gone from the URL.
    expect(window.location.search).not.toContain(`hash=${oldShort}`);
  });
});
