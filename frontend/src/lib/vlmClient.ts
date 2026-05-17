/** U-A3 — VLM dumps HTTP client (master §2.4 rev3). */

export type VlmCallKind = "planner" | "segment";

export interface VlmCall {
  call_id: string;
  kind: VlmCallKind;
  phase: string | null;
  segment_id: string | null;
  prompt: string;
  raw_output: string;
  parsed: unknown;
  failed: boolean;
  ms: number | null;
  model_variant: string | null;
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
