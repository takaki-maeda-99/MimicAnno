// frontend/src/lib/manifest.ts
export type SchemaVersion = `${number}.${number}.${number}`;

export interface InputRef {
  path: string;
  sha256: string;
}

export interface Artifact {
  role: "video" | "annotation" | "boundaries" | "signals";
  url: string;
  content_type: string;
}

export interface PipelineStatus {
  object_state_available: boolean;
  degraded_from_phase: number | null;
  degrade_reason: string | null;
}

export interface BoundaryParams {
  weights: Record<string, number>;
  thresholds: Record<string, number>;
  merge_window_sec: number;
  score_threshold: number;
  disabled_sources: string[];
}

export interface Manifest {
  schema_version: SchemaVersion;
  episode_id: string;
  task: { text: string; version: string | null };
  generated_at: string;
  generator: { name: string; cli_version: string; pipeline_phase: number };
  config_hash: string;
  input_hash: string;
  run_hash: string;
  model_versions: Record<string, string | null>;
  pipeline_params: { boundary: BoundaryParams };
  inputs: { video: InputRef; parquet: InputRef };
  time_base: "video_pts_seconds";
  fps: number;
  duration_sec: number;
  pipeline_status: PipelineStatus;
  compat: { manifest: number; annotation: number; boundaries: number; signals: number };
  artifacts: Artifact[];
}

export interface IndexEntry {
  episode_id: string;
  run_hash: string;
  run_hash_short: string;
  config_hash_short: string;
  input_hash_short: string;
  manifest_url: string;
  task_text: string;
  pipeline_phase: number;
  generated_at: string;
}

export interface IndexDoc {
  schema_version: SchemaVersion;
  runs: IndexEntry[];
}

export interface BoundaryRef {
  candidate_id: string | null;
  time: number;
  sources: string[];
  score: number;
}

export interface BoundaryCandidate {
  id: string;
  frame: number;
  time: number;
  sources: string[];
  scores: Record<string, number>;
  score: number;
}

export interface BoundariesDoc {
  schema_version: SchemaVersion;
  episode_id: string;
  candidates: BoundaryCandidate[];
}

export interface SignalChannel {
  name: string;
  unit: string;
  t0_sec: number;
  dt_sec: number;
  values: number[];
}

export interface SignalsDoc {
  schema_version: SchemaVersion;
  episode_id: string;
  duration_sec: number;
  channels: SignalChannel[];
}

export interface SubtaskSegment {
  segment_id: string;
  episode_id: string;
  start_frame: number;
  end_frame: number;
  start_time: number;
  end_time: number;
  phase: string;
  verb: string | null;
  object: string | null;
  target: string | null;
  failure_flags: string[];
  label_source: string;
  object_state_unavailable: boolean;
  object_track_ids: string[];
  label_version: string;
  start_boundary: BoundaryRef;
  end_boundary: BoundaryRef;
  boundary_confidence: number;
  vlm_confidence: number | null;
  overall_confidence: number;
  evidence: string | null;
  reviewed: boolean;
  reviewer_id: string | null;
}

export interface AnnotationResult {
  schema_version: SchemaVersion;
  episode_id: string;
  task: { text: string; version: string | null };
  generated_at: string;
  generator: { name: string; cli_version: string; pipeline_phase: number };
  config_hash: string;
  input_hash: string;
  run_hash: string;
  model_versions: Record<string, string | null>;
  pipeline_phase: number;
  pipeline_status: PipelineStatus;
  segments: SubtaskSegment[];
  boundaries_url: string;
  signals_url: string;
  notes: string | null;
}

export const SUPPORTED_MAJORS = {
  index: [0] as number[],
  manifest: [0] as number[],
  annotation: [0] as number[],
  boundaries: [0] as number[],
  signals: [0] as number[],
} as const;

export function artifactUrl(
  manifest: Manifest,
  role: Artifact["role"],
): string {
  const a = manifest.artifacts.find((x) => x.role === role);
  if (!a) {
    throw new Error(`no artifact with role ${JSON.stringify(role)} in manifest`);
  }
  return a.url;
}

export function resolveUrl(baseUrl: string, relative: string): string {
  return new URL(relative, baseUrl).toString();
}

function major(version: SchemaVersion): number {
  const m = parseInt(version.split(".")[0], 10);
  if (Number.isNaN(m)) {
    throw new Error(
      `schema_version ${JSON.stringify(version)} has non-integer major`,
    );
  }
  return m;
}

export function assertIndexSchema(
  doc: { schema_version: SchemaVersion },
  supportedMajors: number[],
): void {
  const m = major(doc.schema_version);
  if (!supportedMajors.includes(m)) {
    throw new Error(
      `runs/index.json schema major ${m}; viewer reads majors {${supportedMajors.join(",")}}`,
    );
  }
}

export function assertConsumerCapability(
  manifest: Manifest,
  supported: typeof SUPPORTED_MAJORS,
): void {
  const manifestMajor = major(manifest.schema_version);
  if (!supported.manifest.includes(manifestMajor)) {
    throw new Error(
      `manifest.json schema major ${manifestMajor}; viewer reads majors {${supported.manifest.join(",")}}`,
    );
  }
  for (const role of ["annotation", "boundaries", "signals"] as const) {
    const claimed = manifest.compat[role];
    if (!supported[role].includes(claimed)) {
      throw new Error(
        `this run uses schema major ${claimed} for ${role}; this viewer reads majors {${supported[role].join(",")}}. update viewer.`,
      );
    }
  }
}

export function assertArtifactSelfConsistent(
  role: "annotation" | "boundaries" | "signals",
  artifact: { schema_version: SchemaVersion },
  manifest: Manifest,
): void {
  const actual = major(artifact.schema_version);
  const claimed = manifest.compat[role];
  if (actual !== claimed) {
    throw new Error(
      `${role}.json claims schema major ${actual} but manifest.compat says ${claimed}. run directory is internally corrupt.`,
    );
  }
}
