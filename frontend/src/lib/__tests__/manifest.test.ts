import { describe, it, expect } from "vitest";
import {
  artifactUrl,
  resolveUrl,
  assertIndexSchema,
  assertConsumerCapability,
  assertArtifactSelfConsistent,
  SUPPORTED_MAJORS,
} from "../manifest";
import type { AnnotationResult, IndexDoc, Manifest } from "../manifest";
import realManifest from "./fixtures/manifest.json";
import realAnnotation from "./fixtures/annotation.json";
import realIndex from "./fixtures/index.json";

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

describe("assertIndexSchema", () => {
  it("passes on a supported major", () => {
    expect(() =>
      assertIndexSchema(realIndex as IndexDoc, SUPPORTED_MAJORS.index),
    ).not.toThrow();
  });
  it("throws on an unsupported major", () => {
    const bad: IndexDoc = {
      ...(realIndex as IndexDoc),
      schema_version: "9.0.0",
    };
    expect(() => assertIndexSchema(bad, SUPPORTED_MAJORS.index)).toThrow(
      /major/i,
    );
  });
});

describe("assertConsumerCapability", () => {
  it("passes on a valid manifest", () => {
    expect(() =>
      assertConsumerCapability(realManifest as Manifest, SUPPORTED_MAJORS),
    ).not.toThrow();
  });
  it("throws when manifest's own schema_version major is unsupported", () => {
    const bad = {
      ...(realManifest as Manifest),
      schema_version: "9.0.0" as const,
    };
    expect(() => assertConsumerCapability(bad, SUPPORTED_MAJORS)).toThrow(
      /manifest.*major 9/,
    );
  });
  it("throws when manifest.compat.annotation is unsupported", () => {
    const bad = {
      ...(realManifest as Manifest),
      compat: { ...(realManifest as Manifest).compat, annotation: 99 },
    };
    expect(() => assertConsumerCapability(bad, SUPPORTED_MAJORS)).toThrow(
      /annotation/,
    );
  });
});

describe("assertArtifactSelfConsistent", () => {
  it("passes when artifact.schema_version.major matches manifest.compat[role]", () => {
    expect(() =>
      assertArtifactSelfConsistent(
        "annotation",
        realAnnotation as AnnotationResult,
        realManifest as Manifest,
      ),
    ).not.toThrow();
  });
  it("throws when artifact major disagrees with manifest.compat[role]", () => {
    const bad = {
      ...(realAnnotation as AnnotationResult),
      schema_version: "9.0.0" as const,
    };
    expect(() =>
      assertArtifactSelfConsistent(
        "annotation",
        bad,
        realManifest as Manifest,
      ),
    ).toThrow(/9 .* 0/);
  });
});

describe("real fixture", () => {
  it("parses and has the expected core fields", () => {
    const m = realManifest as Manifest;
    expect(m.time_base).toBe("video_pts_seconds");
    expect(m.compat).toEqual({
      manifest: 0,
      annotation: 0,
      boundaries: 0,
      signals: 0,
    });
    expect(m.artifacts.length).toBe(4);
    expect(m.artifacts.map((a) => a.role).sort()).toEqual([
      "annotation",
      "boundaries",
      "signals",
      "video",
    ]);
  });
});
