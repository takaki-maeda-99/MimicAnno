/** U-A4 — SAM3 mask overlay HTTP client. */

export interface MaskTrack {
  track_id: string;
  prompt: string;
  role: string;
  color: string;       // hex e.g. "#1f77b4"
  first_frame: number; // -1 for gap-only / empty tracks
  last_frame: number;  // -1 for gap-only / empty tracks
}

export interface MasksMeta {
  run_set: string;
  canonical: string;
  frame_count: number;
  shape: [number, number];
  tracks: MaskTrack[];
}

/**
 * Fetch mask metadata for one canonical run.
 *
 * Returns null when the server returns 204 (legacy run, no sidecar).
 * Throws on network error or non-2xx/204 status.
 */
export async function fetchMasksMeta(
  apiBase: string,
  runName: string,
  runSet: string,
  signal?: AbortSignal,
): Promise<MasksMeta | null> {
  const url =
    `${apiBase}/api/runs/${encodeURIComponent(runName)}/masks/meta.json` +
    `?run_set=${encodeURIComponent(runSet)}`;
  const r = await fetch(url, { signal });
  if (r.status === 204) return null;
  if (!r.ok) throw new Error(`masks/meta.json fetch failed: ${r.status}`);
  return (await r.json()) as MasksMeta;
}

/**
 * Build the URL for a specific frame's mask PNG.
 * The component fetches this with a plain <img> or via fetch.
 */
export function maskPngUrl(
  apiBase: string,
  runName: string,
  frame: number,
  runSet: string,
): string {
  return (
    `${apiBase}/api/runs/${encodeURIComponent(runName)}/masks/${frame}` +
    `?run_set=${encodeURIComponent(runSet)}`
  );
}
