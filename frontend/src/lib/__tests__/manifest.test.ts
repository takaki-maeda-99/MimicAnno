import { describe, it, expect } from "vitest";
import { artifactUrl, resolveUrl } from "../manifest";
import type { Manifest } from "../manifest";

const fakeManifest: Manifest = {
  schema_version: "0.1.0",
  episode_id: "ep_000",
  task: { text: "x", version: null },
  generated_at: "2026-04-26T00:00:00Z",
  generator: { name: "mimicanno", cli_version: "0.1.0", pipeline_phase: 1 },
  config_hash: "sha256:c", input_hash: "sha256:i", run_hash: "sha256:r",
  model_versions: { sam3: null, vlm: null },
  pipeline_params: { boundary: { weights: {}, thresholds: {}, merge_window_sec: 0.1, score_threshold: 0.3, disabled_sources: [] } },
  inputs: { video: { path: "v.mp4", sha256: "sha256:v" }, parquet: { path: "p.parquet", sha256: "sha256:p" } },
  time_base: "video_pts_seconds",
  fps: 30, duration_sec: 10,
  pipeline_status: { object_state_available: false, degraded_from_phase: null, degrade_reason: null },
  compat: { manifest: 1, annotation: 1, boundaries: 1, signals: 1 },
  artifacts: [
    { role: "video", url: "video.mp4", content_type: "video/mp4" },
    { role: "annotation", url: "annotation.json", content_type: "application/json" },
    { role: "boundaries", url: "boundaries.json", content_type: "application/json" },
    { role: "signals", url: "signals.json", content_type: "application/json" },
  ],
};

describe("artifactUrl", () => {
  it("returns the URL for a present role", () => {
    expect(artifactUrl(fakeManifest, "annotation")).toBe("annotation.json");
  });
  it("throws if the role is missing", () => {
    const m = { ...fakeManifest, artifacts: [] };
    expect(() => artifactUrl(m, "annotation")).toThrow(/no artifact with role/);
  });
});

describe("resolveUrl", () => {
  it("resolves a relative manifest_url against a directory base", () => {
    expect(
      resolveUrl("http://localhost:5173/runs/", "ep_000__abc/manifest.json"),
    ).toBe("http://localhost:5173/runs/ep_000__abc/manifest.json");
  });
  it("resolves an artifact url against a manifest URL", () => {
    expect(
      resolveUrl(
        "http://localhost:5173/runs/ep_000__abc/manifest.json",
        "boundaries.json",
      ),
    ).toBe("http://localhost:5173/runs/ep_000__abc/boundaries.json");
  });
});
