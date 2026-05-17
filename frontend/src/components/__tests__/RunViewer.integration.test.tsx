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

describe("RunViewer back link — preserves apiEnabled (PR3 follow-up)", () => {
  it("apiEnabled=true → ← runs href points at /?api=1", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/api/runs/index.json")) return jsonResp(INDEX_DOC);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST);
      if (url.endsWith("/annotation.json")) return jsonResp(ANNOTATION);
      if (url.endsWith("/boundaries.json")) return jsonResp(BOUNDARIES);
      if (url.endsWith("/signals.json")) return jsonResp(SIGNALS);
      if (url.endsWith("/api/labelset")) return jsonResp(LABELSET);
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );
    const link = await screen.findByText("← runs");
    expect(link.getAttribute("href")).toBe("/?api=1");
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

describe("RunViewer error toast composition (spec §3.5)", () => {
  // Helper: render RunViewer up to the first edit, then trigger a PATCH
  // that returns the given mocked response (or rejects).
  async function renderAndEditWith(
    patchResponseFactory: () => Response | Promise<never>,
  ): Promise<void> {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/api/runs/index.json")) return jsonResp(INDEX_DOC);
      if (url.endsWith("/manifest.json")) return jsonResp(MANIFEST);
      if (url.endsWith("/annotation.json")) return jsonResp(ANNOTATION);
      if (url.endsWith("/boundaries.json")) return jsonResp(BOUNDARIES);
      if (url.endsWith("/signals.json")) return jsonResp(SIGNALS);
      if (url.endsWith("/api/labelset")) return jsonResp(LABELSET);
      if (url.includes("/segments/")) return patchResponseFactory();
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );
    const sel = (await screen.findByLabelText(
      "phase for seg-001",
    )) as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(sel, { target: { value: "grasp_object" } });
    });
  }

  it("500 with envelope {error, message} → toast prefix is the error code, NOT 'HTTP 500'", async () => {
    // BLOCKER caught in code review of the smoke plan: the kind:"error"
    // branch in RunViewer was formatting as `HTTP ${httpStatus}: ${message}`,
    // dropping the server's `error` field. spec §3.5 requires the
    // server's error code to surface. The fix maps `errorCode` to the
    // toast prefix when present.
    await renderAndEditWith(() =>
      new Response(
        JSON.stringify({ error: "internal", message: "kapow" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("internal");
    expect(alert.textContent).toContain("kapow");
    expect(alert.textContent).not.toContain("HTTP 500");
  });

  it("500 without an envelope (just text body) → toast falls back to 'HTTP 500'", async () => {
    // Defensive: if the server returns something that isn't the {error,
    // message} shape, we still want a meaningful toast. The fallback
    // path uses HTTP <status>.
    await renderAndEditWith(() =>
      new Response("internal explosion", { status: 500 }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("HTTP 500");
  });

  it("network failure (fetch rejects) → toast shows the error, editInFlight clears (E6 coverage)", async () => {
    // E6 from the UI smoke matrix: killing the backend mid-PATCH should
    // surface a toast and re-enable the dropdowns via the finally clause.
    // We simulate by making fetch reject. Asserting on editInFlight is
    // observable through dropdown disabled state.
    await renderAndEditWith(() => Promise.reject(new Error("fetch failed")));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/fetch failed/);
    // editInFlight cleared in finally → selects re-enabled.
    await waitFor(() => {
      const selects = screen.getAllByRole("combobox");
      for (const s of selects) {
        expect((s as HTMLSelectElement).disabled).toBe(false);
      }
    });
  });
});

describe("D r2 timing integration — body propagation", () => {
  it("I1: phase edit PATCH body carries client_edit_duration_ms from performance.now", async () => {
    // performance.now spy must be installed BEFORE render so that
    // startEdit("phase") on the first focus event reads our stub value.
    let perfNowValue = 1000;
    const perfSpy = vi
      .spyOn(performance, "now")
      .mockImplementation(() => perfNowValue);

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

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    const sel = (await screen.findByLabelText(
      "phase for seg-001",
    )) as HTMLSelectElement;

    // Focus → startEdit("phase") stores perfNowValue (1000).
    await act(async () => {
      fireEvent.focus(sel);
    });
    // Advance clock: consumeEdit will compute 1500 - 1000 = 500 ms.
    perfNowValue = 1500;
    // Change → handlePhaseChange → consumeEdit → PATCH body.
    await act(async () => {
      fireEvent.change(sel, { target: { value: "grasp_object" } });
    });

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
    });

    const patchCall = fetchMock.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    )!;
    const body = JSON.parse((patchCall[1] as RequestInit).body as string);
    expect(body.client_edit_duration_ms).toBe(500);

    perfSpy.mockRestore();
  });

  it("I2: labels blur-commit PATCH carries client_edit_duration_ms across async-await boundary", async () => {
    // performance.now spy installed BEFORE render — startEdit("labels") on
    // the verb input's onFocus will read our stub value (1000).
    let perfNowValue = 1000;
    const perfSpy = vi
      .spyOn(performance, "now")
      .mockImplementation(() => perfNowValue);

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

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    const verbInput = (await screen.findByLabelText(
      "verb for seg-001",
    )) as HTMLInputElement;

    // Focus → startEdit("labels") stores perfNowValue (1000).
    await act(async () => {
      fireEvent.focus(verbInput);
    });
    // Change the verb so labelsChanged() returns true (otherwise early-return
    // path would skip the PATCH, though duration is still consumed synchronously).
    await act(async () => {
      fireEvent.change(verbInput, { target: { value: "cup" } });
    });
    // Advance clock to 2000: consumeEdit in handleLabelBlur will compute
    // 2000 - 1000 = 1000 ms. This happens synchronously at function entry
    // before the `await onLabelsEdit(...)` call — spec §3.3 contract.
    perfNowValue = 2000;
    await act(async () => {
      fireEvent.blur(verbInput);
    });

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit | undefined)?.method === "PATCH" &&
          typeof c[0] === "string" &&
          (c[0] as string).includes("/labels"),
      );
      expect(patchCall).toBeDefined();
    });

    const patchCall = fetchMock.mock.calls.find(
      (c) =>
        (c[1] as RequestInit | undefined)?.method === "PATCH" &&
        typeof c[0] === "string" &&
        (c[0] as string).includes("/labels"),
    )!;
    const body = JSON.parse((patchCall[1] as RequestInit).body as string);
    // Synchronous capture before await: 2000 - 1000 = 1000 ms.
    expect(body.client_edit_duration_ms).toBe(1000);

    perfSpy.mockRestore();
  });
});

describe("D r2 timing — performance.now() migration", () => {
  it("T5: client_edit_duration_ms remains non-negative under wall-clock skew", async () => {
    // Wall clock decreases (e.g. NTP slew correcting a fast clock) between
    // focus and commit. With Date.now() the duration would be negative;
    // performance.now() is monotonic so it stays non-negative.
    //
    // We install the performance.now mock only AFTER the initial render
    // settles, because React/jsdom internals call performance.now during
    // setup and would otherwise consume our mockReturnValueOnce values.
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

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort={undefined} />
      </ApiToggleProvider>,
    );

    const sel = (await screen.findByLabelText(
      "phase for seg-001",
    )) as HTMLSelectElement;

    // Install timing spies AFTER render settles. React/jsdom call
    // performance.now and Date.now many times incidentally, so we use a
    // controllable counter rather than mockReturnValueOnce (which would
    // be consumed by unrelated callers). We bump the counters manually
    // between the focus and commit events.
    let perfNowValue = 1000;
    const perfSpy = vi
      .spyOn(performance, "now")
      .mockImplementation(() => perfNowValue);
    // Simulate wall-clock going backward between focus and commit.
    let dateNowValue = 200;
    const dateSpy = vi
      .spyOn(Date, "now")
      .mockImplementation(() => dateNowValue);

    // Focus event → onEditFocus → editStartRef.current = now() (1000)
    await act(async () => {
      fireEvent.focus(sel);
    });
    // Advance: perf.now monotonic forward, Date.now backward (NTP slew).
    perfNowValue = 1500;
    dateNowValue = 100;
    // Commit → duration calc = now() - editStartRef.current
    await act(async () => {
      fireEvent.change(sel, { target: { value: "grasp_object" } });
    });

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
    });

    const patchCall = fetchMock.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    )!;
    const body = JSON.parse((patchCall[1] as RequestInit).body as string);
    // Monotonic: 1500 - 1000 = 500. Non-negative is the load-bearing
    // assertion; the exact value (500, not Date.now's -100) proves the
    // path uses performance.now, not Date.now.
    expect(body.client_edit_duration_ms).toBeGreaterThanOrEqual(0);
    expect(body.client_edit_duration_ms).toBe(500);
    // Both spies are exercised incidentally by React/jsdom too — we only
    // assert the duration value, which is the load-bearing behaviour.
    expect(perfSpy).toHaveBeenCalled();
    expect(dateSpy).toHaveBeenCalled();

    perfSpy.mockRestore();
    dateSpy.mockRestore();
  });
});

describe("RunViewer merged-mode reload (no ?run_set= in URL)", () => {
  it("uses selected entry's run_set for manifest + artifact fetches", async () => {
    // Reload at /?api=1&run=ep0&hash=aaaaaaaa (no &run_set=).
    // Backend returns a merged index where the entry has run_set='so101_phase4_v5'.
    // Manifest + artifact fetches must thread that run_set, not the (absent) URL one.
    const MERGED_INDEX = {
      ...INDEX_DOC,
      runs: [{ ...INDEX_DOC.runs[0], run_set: "so101_phase4_v5" }],
    };
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url ?? input.toString();
      if (url.endsWith("/api/runs/index.json")) return jsonResp(MERGED_INDEX);
      if (url.includes("/manifest.json")) return jsonResp(MANIFEST);
      if (url.includes("/annotation.json")) return jsonResp(ANNOTATION);
      if (url.includes("/boundaries.json")) return jsonResp(BOUNDARIES);
      if (url.includes("/signals.json")) return jsonResp(SIGNALS);
      if (url.endsWith("/api/labelset")) return jsonResp(LABELSET);
      if (url.includes("/vlm_dumps.json")) return jsonResp({ calls: [] });
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(
      <ApiToggleProvider apiEnabled={true}>
        <RunViewer episodeId="ep0" runHashShort="aaaaaaaa" />
      </ApiToggleProvider>,
    );

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([u]) =>
        typeof u === "string" ? u : (u as Request).url ?? u.toString(),
      );
      // Manifest fetch carries run_set from the entry (not from URL).
      const manifestCall = urls.find((u) => u.includes("manifest.json"));
      expect(manifestCall).toBeDefined();
      expect(manifestCall).toContain("run_set=so101_phase4_v5");
      // Annotation fetch likewise threaded.
      const annotationCall = urls.find((u) => u.includes("annotation.json"));
      expect(annotationCall).toBeDefined();
      expect(annotationCall).toContain("run_set=so101_phase4_v5");
    });
  });
});
