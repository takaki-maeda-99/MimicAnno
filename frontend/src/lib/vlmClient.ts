/** U-A3 — VLM dumps HTTP client (master §2.4 rev3). */

export type VlmCallKind = "planner" | "labeler";

export interface VlmCall {
  kind: VlmCallKind;
  call_id: string;
  attempt: number | null;
  prompt: string;
  raw_output: string;
  parsed: unknown;
  failed: boolean;
  /** Planner-only: URL to the frame image. Null for labeler. */
  frame_url: string | null;
  /** Labeler-only: 0-based segment ordinal. Null for planner. */
  segment_ordinal: number | null;
  /** Labeler-only: parsed request.json or null if absent. */
  request_json: unknown;
  /** Labeler-only: sorted keyframe image URLs. Empty for planner. */
  keyframe_urls: string[];
}

export interface VlmDumps {
  canonical: string;
  run_set: string;
  episode_id: string;
  calls: VlmCall[];
}

/** Fetch VLM dumps for one canonical in a given run-set.
 *
 *  Throws on non-200 (caller catches and shows error state).
 */
export async function fetchVlmDumps(args: {
  apiBase: string;
  canonical: string;
  runSet: string;
  signal?: AbortSignal;
}): Promise<VlmDumps> {
  const { apiBase, canonical, runSet, signal } = args;
  const url =
    `${apiBase}/api/runs/${encodeURIComponent(canonical)}/vlm_dumps.json` +
    `?run_set=${encodeURIComponent(runSet)}`;
  const r = await fetch(url, { signal });
  if (!r.ok) {
    throw new Error(`vlm_dumps fetch failed: ${r.status}`);
  }
  return (await r.json()) as VlmDumps;
}
