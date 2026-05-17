/**
 * U-A2 — API client for GET /api/datasets/{name}/summary (spec §2.2).
 */

export interface SegmentCountStats {
  mean: number;
  min: number;
  max: number;
}

export interface PerEpisodeSummary {
  idx: number;
  canonical: string;
  segment_count: number;
  reviewed_count: number;
  label_diversity: number;
}

export interface DatasetSummary {
  run_set: string;
  ep_count: number;
  annotated_ep_count: number;
  label_distribution: Record<string, number>;
  segment_count_stats: SegmentCountStats;
  reviewed_rate: number;
  per_episode: PerEpisodeSummary[];
}

const API_BASE = "/api";

export async function fetchDatasetSummary(
  name: string,
  runSet?: string,
): Promise<DatasetSummary> {
  let url = `${API_BASE}/datasets/${encodeURIComponent(name)}/summary`;
  if (runSet) {
    url += `?run_set=${encodeURIComponent(runSet)}`;
  }
  const r = await fetch(url);
  if (!r.ok) {
    const err = await r.json().catch(() => ({})) as { message?: string };
    throw new Error(
      err.message ?? `GET /api/datasets/${name}/summary failed: HTTP ${r.status}`,
    );
  }
  return r.json() as Promise<DatasetSummary>;
}
