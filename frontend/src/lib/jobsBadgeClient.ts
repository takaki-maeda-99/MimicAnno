/**
 * U-A5 — Fetcher for the site-wide running-jobs count badge.
 * Calls GET /api/jobs?status=running and returns the count.
 * Errors are swallowed and return 0 (badge hides rather than showing error state).
 */

const API_BASE = "/api";

/**
 * Returns the number of currently running jobs.
 * Returns 0 on any fetch/network error.
 */
export async function fetchRunningCount(): Promise<number> {
  try {
    const r = await fetch(`${API_BASE}/jobs?status=running`);
    if (!r.ok) return 0;
    const jobs = (await r.json()) as unknown[];
    return jobs.length;
  } catch {
    return 0;
  }
}
