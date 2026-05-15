/**
 * Phase 5 B r1 T13.5 — labelset GET + module-scope memoisation.
 *
 * The server already caches /api/labelset for 300 s; client-side cache
 * dedupes the per-tab redundant request. Keyed by apiBase so that
 * /api/runs/ and a hypothetical /api/runs-v2/ don't share a cache.
 *
 * Returns the parsed Promise — concurrent callers receive the same
 * in-flight Promise (closes the strict-mode double-effect race).
 */
import { fetchRetry } from "./fetchRetry";

export interface LabelSetEntry {
  id: string;
  requires_object: boolean;
}

export interface LabelSetDoc {
  labels: LabelSetEntry[];
  labels_yaml_sha256: string;
}

const cache = new Map<string, Promise<LabelSetDoc>>();

function labelsetUrl(apiBase: string): string {
  // /api/runs/ → /api/labelset (sibling under the API root)
  return apiBase.replace(/\/runs\/?$/, "/labelset");
}

export function loadLabelset(apiBase: string): Promise<LabelSetDoc> {
  const cached = cache.get(apiBase);
  if (cached !== undefined) return cached;
  const p = (async () => {
    const resp = await fetchRetry(labelsetUrl(apiBase));
    if (!resp.ok) {
      // Evict on failure so the next call retries.
      cache.delete(apiBase);
      throw new Error(`labelset fetch failed: HTTP ${resp.status}`);
    }
    return (await resp.json()) as LabelSetDoc;
  })();
  cache.set(apiBase, p);
  // Also evict on promise rejection so the next attempt can retry.
  p.catch(() => cache.delete(apiBase));
  return p;
}

export function __resetLabelsetCacheForTests(): void {
  cache.clear();
}
