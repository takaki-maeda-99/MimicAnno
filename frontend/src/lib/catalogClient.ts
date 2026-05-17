/**
 * U-A1 — API client for /api/datasets and /api/jobs.
 */

export interface RunRef {
  canonical: string;
  run_hash: string;
  run_set: string;
  pipeline_phase: number;
  generated_at: string;
}

export interface EpisodeInfo {
  idx: number;
  video_path: string;
  parquet_path: string;
  frame_count: number | null;
  fps: number | null;
  runs: RunRef[];
}

export interface DatasetInfo {
  name: string;
  path: string;
  ep_count: number;
  annotated_ep_count: number;
  robot_hint: string | null;
  task_text_hint: string | null;
  videos_root: string | null;
  last_modified: string;
}

export interface DatasetDetail {
  name: string;
  path: string;
  episodes: EpisodeInfo[];
}

export interface JobSummary {
  job_id: string;
  status: string;
  dataset: string;
  progress_pct: number | null;
  current_episode_idx: number | null;
  started_at: string | null;
  finished_at: string | null;
  run_canonicals: string[];
}

export interface JobDetail extends JobSummary {
  kind: string;
  episode_indices: number[];
  run_set: string;
  variant: string;
  gpu_index: number;
  robot_config: string;
  pipeline_config: string;
  queued_at: string | null;
  log_tail: string[];
  log_url: string;
  error: { reason: string; detail?: string } | null;
}

export interface PostJobBody {
  kind?: string;
  dataset: string;
  episode_indices?: number[] | null;
  robot_config: string;
  pipeline_config: string;
  run_set: string;
  gpu_index?: number | null;
  variant?: string;
}

const API_BASE = "/api";

export async function fetchDatasets(): Promise<DatasetInfo[]> {
  const r = await fetch(`${API_BASE}/datasets`);
  if (!r.ok) throw new Error(`GET /api/datasets failed: HTTP ${r.status}`);
  return r.json() as Promise<DatasetInfo[]>;
}

export async function fetchDataset(name: string): Promise<DatasetDetail> {
  const r = await fetch(`${API_BASE}/datasets/${encodeURIComponent(name)}`);
  if (!r.ok) throw new Error(`GET /api/datasets/${name} failed: HTTP ${r.status}`);
  return r.json() as Promise<DatasetDetail>;
}

export async function fetchJobs(status?: string[]): Promise<JobSummary[]> {
  let url = `${API_BASE}/jobs`;
  if (status && status.length > 0) {
    const params = status.map((s) => `status=${encodeURIComponent(s)}`).join("&");
    url += `?${params}`;
  }
  const r = await fetch(url);
  if (!r.ok) throw new Error(`GET /api/jobs failed: HTTP ${r.status}`);
  return r.json() as Promise<JobSummary[]>;
}

export async function fetchJob(jobId: string): Promise<JobDetail> {
  const r = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
  if (!r.ok) throw new Error(`GET /api/jobs/${jobId} failed: HTTP ${r.status}`);
  return r.json() as Promise<JobDetail>;
}

export async function postJob(
  body: PostJobBody,
): Promise<{ job_id: string; status: string }> {
  const r = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.status === 409) {
    const err = await r.json() as { message?: string };
    throw new Error(
      err.message ?? "run_set already has overlapping runs. Choose a different run_set name.",
    );
  }
  if (!r.ok) {
    const err = await r.json() as { message?: string };
    throw new Error(err.message ?? `POST /api/jobs failed: HTTP ${r.status}`);
  }
  return r.json() as Promise<{ job_id: string; status: string }>;
}

export async function deleteJob(jobId: string): Promise<void> {
  const r = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`DELETE /api/jobs/${jobId} failed: HTTP ${r.status}`);
  }
}
